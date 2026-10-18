import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import (
    assets,
    figma,
    finishing,
    generate,
    health,
    history,
    photo_first,
    projects,
    references,
    scene,
    structure,
)
from app.config import get_settings
from app.errors import ErrorResponse, install_error_handlers
from app.jobs.runner import reap_orphans
from app.storage.db import init_db

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    init_db(get_settings().db_path)
    reap_orphans()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Dieline Studio API",
        version="0.1.0",
        lifespan=lifespan,
        # Documents the shared error shape on every route in the OpenAPI schema.
        responses={"default": {"model": ErrorResponse}},
    )
    install_error_handlers(app)
    for r in (
        health.router,
        figma.router,
        projects.router,
        references.router,
        generate.router,
        history.router,
        assets.router,
        finishing.router,
        structure.router,
        scene.router,
        photo_first.router,
    ):
        app.include_router(r, prefix="/api")
    return app


app = create_app()
