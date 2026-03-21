"""FastAPI application entry point: app creation, lifespan, and router registration."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from . import crud, models
from .config import LIBRARY_PATH
from .database import SessionLocal, engine
from .logging_config import setup_logging
from .routers import api_keys, books, cleaning, covers, reader, scheduler, storage, upload, web_novels
from .services.web_import_queue import get_web_import_queue
from .services.update_scheduler import get_scheduler, schedule_next_web_novel_update

logger = logging.getLogger(__name__)

_mem_handler = setup_logging()
_scheduler = get_scheduler()
_web_import_queue = get_web_import_queue()


async def _create_tables() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(models.Base.metadata.create_all)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Re-attach memory handler after uvicorn resets logging config on startup
    root_logger = logging.getLogger()
    if _mem_handler not in root_logger.handlers:
        root_logger.addHandler(_mem_handler)
    logger.info("Starting up and creating database tables if they don't exist.")
    await _create_tables()
    async with SessionLocal() as db:
        await crud.reset_stuck_update_tasks(db)
    await _web_import_queue.start()
    requeued = await _web_import_queue.requeue_pending_books()
    if requeued:
        logger.info("Re-queued %s pending web novel imports.", requeued)
    if not _scheduler.running:
        _scheduler.start()
    await schedule_next_web_novel_update()
    yield
    await _web_import_queue.stop()
    if _scheduler.running:
        _scheduler.shutdown()


app = FastAPI(title="Story Manager", lifespan=lifespan)
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


@app.get("/")
def read_root() -> dict:
    return {"message": "Welcome to the Story Manager API"}
