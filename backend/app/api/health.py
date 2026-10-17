from fastapi import APIRouter
from pydantic import BaseModel

from app.config import get_settings
from app.storage.db import connect

router = APIRouter(tags=["system"])


class Health(BaseModel):
    status: str
    database: str


@router.get("/health", response_model=Health)
def health() -> Health:
    with connect(get_settings().db_path) as conn:
        conn.execute("SELECT 1")
    return Health(status="ok", database="ok")
