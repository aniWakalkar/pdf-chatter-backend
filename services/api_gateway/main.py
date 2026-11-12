import logging
import uuid
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.background import BackgroundTask

from services.api_gateway.rate_limit import SlidingWindowLimiter, match_rule
from shared.config import get_settings
from shared.security import decode_access_token

logger = logging.getLogger("api-gateway")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

settings = get_settings()

ROUTES: list[tuple[str, str]] = [
    ("/api/auth", settings.auth_service_url),
    ("/api/documents", settings.document_service_url),
    ("/api/conversations", settings.chat_service_url),
    ("/api/chat", settings.chat_service_url),
]
PUBLIC_ENDPOINTS = {("POST", "/api/auth/register"), ("POST", "/api/auth/login")}
HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
}
STRIPPED_REQUEST_HEADERS = HOP_BY_HOP | {"authorization", "x-user-id", "x-internal-token", "cookie"}
MAX_BODY_BYTES = settings.max_upload_bytes + 1024 * 1024

limiter = SlidingWindowLimiter()


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.client = httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=5.0))
    yield
    await app.state.client.aclose()


app = FastAPI(title="api-gateway", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    expose_headers=["x-request-id", "retry-after"],
)


def _resolve_service(path: str) -> str | None:
    for prefix, base_url in ROUTES:
        if path == prefix or path.startswith(prefix + "/"):
            return base_url
    return None


def _error(status_code: int, detail: str, request_id: str, headers: dict | None = None) -> JSONResponse:
    response = JSONResponse({"detail": detail}, status_code=status_code, headers=headers)
    response.headers["x-request-id"] = request_id
    return response


@app.get("/api/health")
async def health(request: Request):
    client: httpx.AsyncClient = request.app.state.client
    services = {
        "auth-service": settings.auth_service_url,
        "document-service": settings.document_service_url,
        "chat-service": settings.chat_service_url,
    }
    result = {}
    for name, url in services.items():
        try:
            response = await client.get(f"{url}/health", timeout=3.0)
            result[name] = "ok" if response.status_code == 200 else "error"
        except httpx.HTTPError:
            result[name] = "unreachable"
    healthy = all(v == "ok" for v in result.values())
    return JSONResponse({"status": "ok" if healthy else "degraded", "services": result})


@app.api_route("/api/{path:path}", methods=["GET", "POST", "PATCH", "DELETE"])
async def proxy(request: Request, path: str):
    request_id = str(uuid.uuid4())
    full_path = f"/api/{path}"
    method = request.method.upper()

    target = _resolve_service(full_path)
    if target is None:
        return _error(404, "Not found", request_id)

    user_id: uuid.UUID | None = None
    if (method, full_path.rstrip("/")) not in PUBLIC_ENDPOINTS:
        auth_header = request.headers.get("authorization", "")
        scheme, _, token = auth_header.partition(" ")
        if scheme.lower() == "bearer" and token:
            user_id = decode_access_token(token.strip())
        if user_id is None:
            return _error(401, "Not authenticated", request_id, {"WWW-Authenticate": "Bearer"})

    rule = match_rule(method, full_path)
    if rule:
        client_ip = request.client.host if request.client else "unknown"
        key = f"{method}:{full_path}:{user_id or client_ip}"
        allowed, retry_after = limiter.allow(key, *rule)
        if not allowed:
            return _error(429, "Too many requests. Please slow down.", request_id, {"Retry-After": str(retry_after)})

    declared_length = request.headers.get("content-length")
    if declared_length and declared_length.isdigit() and int(declared_length) > MAX_BODY_BYTES:
        return _error(413, f"Request is larger than {settings.max_upload_mb} MB.", request_id)
    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        return _error(413, f"Request is larger than {settings.max_upload_mb} MB.", request_id)

    headers = {k: v for k, v in request.headers.items() if k.lower() not in STRIPPED_REQUEST_HEADERS}
    headers["x-request-id"] = request_id
    headers["x-internal-token"] = settings.internal_service_token
    if user_id:
        headers["x-user-id"] = str(user_id)

    client: httpx.AsyncClient = request.app.state.client
    upstream_request = client.build_request(
        method, f"{target}{full_path}", params=request.query_params, headers=headers, content=body
    )
    try:
        upstream = await client.send(upstream_request, stream=True)
    except httpx.TimeoutException:
        logger.warning("Upstream timeout request_id=%s path=%s", request_id, full_path)
        return _error(504, "The service took too long to respond.", request_id)
    except httpx.HTTPError:
        logger.exception("Upstream unavailable request_id=%s path=%s", request_id, full_path)
        return _error(503, "Service temporarily unavailable.", request_id)

    response_headers = {k: v for k, v in upstream.headers.items() if k.lower() not in HOP_BY_HOP}
    response_headers["x-request-id"] = request_id
    return StreamingResponse(
        upstream.aiter_raw(),
        status_code=upstream.status_code,
        headers=response_headers,
        background=BackgroundTask(upstream.aclose),
    )
