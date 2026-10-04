"""Errors raised by the shared service layer; each interface maps `code` to its own output."""
from __future__ import annotations

from typing import Optional

CODES = (
    "not_found",
    "invalid_reference",
    "duplicate_label",
    "invalid_label",
    "invalid_title",
    "invalid_image",
    "too_large",
    "timeout",
    "referenced_image",
    "invalid_status",
    "bad_query",
    "bad_token",
)


class ServiceError(Exception):
    def __init__(self, code: str, message: str, details: Optional[dict] = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    def as_dict(self) -> dict:
        return {"code": self.code, "message": self.message, **self.details}
