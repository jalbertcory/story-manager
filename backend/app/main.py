"""FastAPI application entry point: app creation, lifespan, and router registration."""

import logging
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI

from . import crud, models
from .database import SessionLocal, engine
from .logging_config import setup_logging
from .routers import api_keys, books, cleaning, covers, reader, scheduler, storage, upload, web_novels
from .services.web_novel import update_web_novels

logger = logging.getLogger(__name__)

_mem_handler = setup_logging()
_scheduler = AsyncIOScheduler()


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
    _scheduler.add_job(update_web_novels, "interval", hours=24)
    _scheduler.start()
    yield
    _scheduler.shutdown()


app = FastAPI(title="Story Manager", lifespan=lifespan)

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
