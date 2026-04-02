"""FastAPI application entry point: app creation, lifespan, and router registration."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from . import crud
from .config import LIBRARY_PATH
from .errors import install_error_handlers
from .middleware import RequestIdMiddleware
from .database import SessionLocal, get_db
from .logging_config import setup_logging
from .routers import api_keys, books, cleaning, covers, metadata, reader, scheduler, storage, upload, web_novels
from .services.metadata_sync_queue import get_metadata_sync_queue
from .services.update_scheduler import get_scheduler, schedule_next_metadata_recheck, schedule_next_web_novel_update
from .services.web_import_queue import get_web_import_queue

logger = logging.getLogger(__name__)

_console_handler, _mem_handler = setup_logging()
_scheduler = get_scheduler()
_web_import_queue = get_web_import_queue()
_metadata_sync_queue = get_metadata_sync_queue()


@asynccontextmanager
async def lifespan(app: FastAPI):
    is_test_app = bool(app.dependency_overrides)
    # Re-attach handlers after uvicorn resets logging config on startup
    root_logger = logging.getLogger()
    if _console_handler not in root_logger.handlers:
        root_logger.addHandler(_console_handler)
    if _mem_handler not in root_logger.handlers:
        root_logger.addHandler(_mem_handler)
    logger.info("Starting up Story Manager services.")
    async with SessionLocal() as db:
        await crud.reset_stuck_update_tasks(db)
    await _web_import_queue.start()
    if not is_test_app:
        await _metadata_sync_queue.start()
    requeued = await _web_import_queue.requeue_pending_books()
    if requeued:
        logger.info("Re-queued %s pending web novel imports.", requeued)
    if not is_test_app:
        metadata_requeued = await _metadata_sync_queue.requeue_pending_jobs()
        if metadata_requeued:
            logger.info("Re-queued %s pending metadata sync jobs.", metadata_requeued)
    if not _scheduler.running:
        _scheduler.start()
    await schedule_next_web_novel_update()
    if not is_test_app:
        await schedule_next_metadata_recheck()
    yield
    await _web_import_queue.stop()
    if not is_test_app:
        await _metadata_sync_queue.stop()
    if _scheduler.running:
        _scheduler.shutdown()


app = FastAPI(title="Story Manager", lifespan=lifespan)
install_error_handlers(app)
app.add_middleware(RequestIdMiddleware)
app.mount(
    "/library/covers",
    StaticFiles(directory=str((LIBRARY_PATH / "covers").resolve()), check_dir=False),
    name="cover-files",
)

app.include_router(books.router)
app.include_router(upload.router)
app.include_router(web_novels.router)
app.include_router(cleaning.router)
app.include_router(covers.router)
app.include_router(scheduler.router)
app.include_router(storage.router)
app.include_router(api_keys.router)
app.include_router(reader.router)
app.include_router(metadata.router)


@app.get("/health")
async def health_check(db: AsyncSession = Depends(get_db)):
    """Health check endpoint for container orchestration."""
    try:
        await db.execute(text("SELECT 1"))
        return {"status": "healthy", "database": "connected"}
    except Exception as e:
        return JSONResponse(
            status_code=503,
            content={"status": "unhealthy", "database": str(e)},
        )


# Serve the Vite-built frontend in production. The build output lives at
# frontend/dist/ (created by `npm run build` in the Dockerfile). When the
# directory does not exist (local dev), we skip mounting and fall back to a
# simple JSON root response so the Vite dev server can be used via proxy.
_FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"

if _FRONTEND_DIST.is_dir():
    # Serve static assets (JS, CSS, images) at /assets/
    app.mount(
        "/assets",
        StaticFiles(directory=str(_FRONTEND_DIST / "assets"), check_dir=False),
        name="frontend-assets",
    )

    @app.get("/{full_path:path}")
    async def serve_frontend(request: Request, full_path: str):
        """Serve the SPA index.html for any non-API, non-reader path."""
        # Try to serve the exact file first (e.g. favicon.ico, robots.txt)
        file_path = _FRONTEND_DIST / full_path
        if full_path and file_path.is_file() and ".." not in full_path:
            return FileResponse(file_path)
        return FileResponse(_FRONTEND_DIST / "index.html")

else:

    @app.get("/")
    def read_root() -> dict:
        return {"message": "Welcome to the Story Manager API"}
