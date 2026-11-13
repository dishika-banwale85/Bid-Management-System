from contextvars import ContextVar
import re
from urllib.parse import unquote

from fastapi import HTTPException, Request

current_entered_by: ContextVar[str | None] = ContextVar("bidease_entered_by", default=None)
_VALID_NAME = re.compile(r"^[A-Za-z .'-]{2,40}$")


def decode_entered_by(value: str | None) -> str | None:
    if value is None:
        return None
    return unquote(value).strip()


def require_entered_by(request: Request) -> str:
    name = decode_entered_by(request.headers.get("X-Entered-By"))
    if not name or not _VALID_NAME.fullmatch(name):
        raise HTTPException(status_code=400, detail="Please enter your name")
    current_entered_by.set(name)
    request.state.entered_by = name
    return name
