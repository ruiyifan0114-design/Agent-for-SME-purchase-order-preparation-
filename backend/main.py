import logging
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException
from sqlalchemy import text
from backend.api.routes import router
from backend.config import settings
from backend.db.session import engine
from backend.tools.runtime import BusinessError

app = FastAPI(title="Synthetic SME Procurement Agent", version="0.1.0",
              description="Deterministic procurement with explicit human review. All data is synthetic.")
app.add_middleware(CORSMiddleware, allow_origins=settings().cors_origins,
                   allow_methods=["GET", "POST", "PATCH"], allow_headers=["Content-Type", "X-API-Key"])
app.include_router(router)


@app.exception_handler(BusinessError)
async def business_error(_: Request, exc: BusinessError):
    return JSONResponse(status_code=exc.status, content={"error": {"code": exc.code, "message": exc.message}})


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError):
    details = [{"location": list(e["loc"]), "message": e["msg"]} for e in exc.errors()]
    return JSONResponse(status_code=422, content={"error": {"code": "VALIDATION_ERROR", "message": "Invalid request", "details": details}})


@app.exception_handler(HTTPException)
async def http_error(_: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"error": {"code": "HTTP_ERROR", "message": str(exc.detail)}})


@app.exception_handler(Exception)
async def unexpected_error(_: Request, exc: Exception):
    logging.getLogger(__name__).exception("Request failed", exc_info=exc)
    return JSONResponse(status_code=500, content={"error": {"code": "INTERNAL_ERROR", "message": "Operation failed; no success claimed. Check audit/server logs."}})


@app.get("/health")
def health():
    return {"data": {"status": "ok"}}


@app.get("/ready")
def ready():
    with engine.connect() as connection:
        connection.execute(text("SELECT version_num FROM alembic_version"))
    return {"data": {"status": "ready"}}


# The built hash-routed frontend can share one origin with the REST API.
# Register last so API and health routes retain precedence.
frontend_dist = Path(__file__).resolve().parents[1] / "frontend" / "dist"
if frontend_dist.is_dir():
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
