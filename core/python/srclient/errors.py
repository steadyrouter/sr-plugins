"""Errors shown to end users. Nothing here may carry a key or an upstream link."""

from __future__ import annotations

import re

_URL = re.compile(r"(?:https?|ftp)://[^\s\"'<>)\]]+", re.IGNORECASE)
_KEY = re.compile(r"\b(?:sk|key|token)-[A-Za-z0-9_\-]{6,}")
_BEARER = re.compile(r"Bearer\s+\S+", re.IGNORECASE)
_LIMIT = 300


def scrub(text: object, secret: str | None = None) -> str:
    """Remove keys and links from text that came from the gateway or an upstream."""
    out = _URL.sub("[link removed]", str(text or ""))  # links first: a key inside a link goes with the link
    if secret:
        out = out.replace(secret, "[key removed]")
    out = _BEARER.sub("Bearer [key removed]", out)
    out = _KEY.sub("[key removed]", out)
    out = " ".join(out.split())
    return out[:_LIMIT]


class SRError(Exception):
    """A failure the end user can act on. str(err) is always safe to display."""

    def __init__(self, message: str, *, status: int | None = None, code: str | None = None):
        super().__init__(message)
        self.status = status
        self.code = code


class ValidationError(SRError):
    """Rejected before any request was sent, so nothing was charged."""


class VideoFailed(SRError):
    """The task ended in FAILURE. The gateway refunds it."""


class VideoStillRunning(SRError):
    def __init__(self, message: str, *, task_id: str):
        super().__init__(message)
        self.task_id = task_id


class FileTooLarge(SRError):
    def __init__(self, message: str, *, limit: int):
        super().__init__(message)
        self.limit = limit


_BY_CODE = {
    "task_price_unsupported": "This model does not take that resolution, length or input.",
    "insufficient_user_quota": "Your SteadyRouter balance cannot cover this request. Add funds and try again.",
    "model_not_found": "The model name is wrong, or the groups your API key uses do not offer this model.",
}
_BY_STATUS = {
    400: "The request was rejected.",
    401: "The API key is wrong, disabled, expired or out of its spending cap.",
    403: "Your SteadyRouter balance cannot cover this request, or this key may not use this model.",
    404: "The endpoint or model was not found.",
    413: "The request is too large.",
    429: "The service is busy. Try again in a little while.",
    503: "The model name is wrong, or the groups your API key uses do not offer this model.",
}


def from_response(status: int, body: object, secret: str | None = None) -> SRError:
    """Turn an HTTP error reply into a user-facing error."""
    code = detail = None
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict):
            code = err.get("code") or err.get("type")
            detail = err.get("message")
        elif isinstance(err, str):
            detail = err
        code = code or body.get("code")
        detail = detail or body.get("message")
    code = str(code) if code else None
    known = _BY_CODE.get(code or "") or _BY_STATUS.get(status)
    if known and (code in _BY_CODE or status != 400):
        return SRError(known, status=status, code=code)
    clean = scrub(detail, secret)
    base = known or f"The request failed with HTTP {status}."
    return SRError(f"{base} {clean}".strip(), status=status, code=code)
