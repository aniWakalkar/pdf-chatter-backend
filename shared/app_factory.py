import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


def create_service_app(name: str, **kwargs) -> FastAPI:
    logger = logging.getLogger(name)
    app = FastAPI(title=name, **kwargs)

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        request.state.request_id = request_id
        try:
            response = await call_next(request)
        except Exception:
            logger.exception("Unhandled error request_id=%s path=%s", request_id, request.url.path)
            response = JSONResponse({"detail": "Internal server error"}, status_code=500)
        response.headers["x-request-id"] = request_id
        return response

    @app.get("/health", include_in_schema=False)
    def health():
        return {"status": "ok", "service": name}

    return app
