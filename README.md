# PDF Chatter — Backend

FastAPI microservices for a PDF question-answering app using Retrieval-Augmented Generation (RAG). Users upload PDFs, ask questions in plain English, and get answers grounded in their documents with document and page citations.

Frontend: [pdf-chatter-frontend](https://github.com/aniWakalkar/pdf-chatter-frontend)

## Architecture

```
Client
  │  /api/*
  ▼
api-gateway :8000 ── verifies JWT, rate limits, forwards X-User-Id + internal token
   ├── auth-service      :8001  register, login, current user
   ├── document-service  :8002  upload, list, view, retry, delete, ingestion pipeline
   └── chat-service      :8003  conversations, retrieval, grounded answers, citations
        │
        ▼
PostgreSQL + pgvector            shared SQLAlchemy models in shared/
```

Internal services only accept requests carrying the `INTERNAL_SERVICE_TOKEN` added by the gateway, so clients cannot spoof `X-User-Id`.

### Ingestion flow
`uploaded → extracting → indexing → ready / failed`

1. Validate extension, MIME type, size and `%PDF-` signature; save the file and store its path in `documents.storage_key`.
2. Extract text page by page (pypdf), normalise whitespace, skip empty pages.
3. Split each page into ~800-token chunks with ~120-token overlap, keeping exact page numbers.
4. Create 768-dimension embeddings in batches.
5. Replace old chunks and insert new ones in one transaction, so retries never create duplicates.

### Question flow
1. Check that the user owns every selected document; only `ready` documents are searched.
2. Embed the question and run cosine similarity search filtered by `user_id` and selected documents (HNSW index).
3. Drop matches below `MIN_RELEVANCE_SCORE`; if nothing is left, reply that the answer was not found without calling the LLM.
4. Send excerpts (marked as untrusted data) plus recent history to the LLM, which returns JSON `{found, answer, citations}`.
5. Save the question, answer and `message_sources` (filename, page, snippet, score) so citations survive document deletion.

## Tech stack
FastAPI · SQLAlchemy 2 · PostgreSQL + pgvector · pypdf · httpx · PyJWT · bcrypt · Google Gemini or OpenAI (OpenAI-compatible client)

## Project structure

```
services/
  api_gateway/       routing, auth check, rate limiting
  auth_service/      users and JWT
  document_service/  upload, storage, pdf_parser, chunker, ingestion
  chat_service/      retriever, rag, conversations
shared/              config, database, models, security, ai client
database/            schema.sql and migrations
scripts/init_db.py   applies schema.sql
run_all.py           starts all services
```

## Local setup

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # macOS / Linux
pip install -r requirements.txt
cp .env.example .env            # fill in the values
python scripts/init_db.py
python run_all.py               # add --reload during development
```

Gateway: http://127.0.0.1:8000 · Health: http://127.0.0.1:8000/api/health

## Database
Run [database/schema.sql](database/schema.sql) in your PostgreSQL console, or `python scripts/init_db.py`. Tables: `users`, `documents`, `document_chunks`, `conversations`, `messages`, `message_sources`.

## Environment variables

| Variable | Example | Meaning |
|---|---|---|
| DATABASE_URL | postgresql://… | PostgreSQL with pgvector |
| JWT_SECRET | long random string | Signs access tokens |
| INTERNAL_SERVICE_TOKEN | long random string | Gateway → service trust |
| AI_PROVIDER | gemini | `gemini` or `openai` |
| AI_API_KEY | — | Provider API key |
| AI_CHAT_MODEL | gemini-3.5-flash | Answer model |
| AI_FALLBACK_CHAT_MODEL | gemini-3.5-flash-lite | Used when the main model is unavailable |
| AI_REASONING_EFFORT | low | Leave empty for models without reasoning |
| AI_EMBEDDING_MODEL | gemini-embedding-001 | Embedding model |
| EMBEDDING_DIMENSIONS | 768 | Must match `VECTOR(768)` |
| UPLOAD_DIR | ./uploads | PDF storage folder |
| MAX_UPLOAD_MB | 20 | Upload limit |
| CORS_ORIGINS | http://localhost:5173 | Comma-separated frontend origins |
| HOST / PORT | 0.0.0.0 / 8000 | Gateway bind address (set by the host in production) |

## Deployment (Render)

- Runtime: Python 3.13 or Docker (the Dockerfile runs all services in one container).
- Build command: `pip install -r requirements.txt`
- Start command: `HOST=0.0.0.0 python run_all.py`
- Health check path: `/api/health`
- Set every variable above in the Render dashboard, with `CORS_ORIGINS` set to the frontend URL.
- Pick the region closest to your database for low latency.

## API

| Method | Endpoint | Purpose |
|---|---|---|
| POST | /api/auth/register | Create account, returns token |
| POST | /api/auth/login | Sign in, returns token |
| GET | /api/auth/me | Current user |
| POST | /api/documents | Upload PDF (multipart `file`) and start ingestion |
| GET | /api/documents | List documents with status |
| GET | /api/documents/{id} | Document details |
| GET | /api/documents/{id}/file | Stream the PDF (owner only) |
| POST | /api/documents/{id}/retry | Re-run ingestion for a failed document |
| DELETE | /api/documents/{id} | Delete file, chunks and vectors |
| GET | /api/conversations | List conversations |
| POST | /api/conversations | Create conversation |
| GET | /api/conversations/{id} | Conversation details |
| PATCH | /api/conversations/{id} | Rename or change documents |
| DELETE | /api/conversations/{id} | Delete conversation |
| GET | /api/conversations/{id}/messages | Messages with citations |
| POST | /api/chat | Ask a question, returns answer and citations |
| GET | /api/health | Gateway and service health |

## Security
- Passwords hashed with bcrypt; JWT access tokens with expiry.
- Ownership checked on every document, conversation and retrieval query.
- Uploads validated by extension, MIME type, size and file signature; stored outside the web root.
- Document text is treated as untrusted input in prompts.
- Rate limits on login, register, upload and chat.

## Known limitations
- Scanned PDFs are marked failed (no OCR yet).
- Rate limiting is in-memory per gateway instance.
- On hosts with ephemeral disks, uploaded PDF files are lost on restart; indexed text remains searchable.
