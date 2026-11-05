"""Sort a /api/pricing row into a category. Used by the catalog generator and at runtime."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

CATEGORIES = ("language", "image", "video", "music", "audio", "embedding", "rerank")


def _tags(row: Mapping[str, Any]) -> set[str]:
    return {t.strip() for t in (row.get("tags") or "").split(",") if t.strip()}


def classify(row: Mapping[str, Any], overrides: Mapping[str, str] | None = None) -> str:
    name = row.get("model_name", "")
    if overrides and name in overrides:
        return overrides[name]
    tags = _tags(row)
    endpoints = set(row.get("supported_endpoint_types") or [])
    if "Video" in tags or "openai-video" in endpoints:
        return "video"
    if "Image" in tags or "Midjourney" in tags:
        return "image"
    if "Music" in tags:
        return "music"
    if "Audio" in tags:
        return "audio"
    if "Embedding" in tags or "embeddings" in endpoints:
        return "embedding"
    if "Rerank" in tags or "jina-rerank" in endpoints:
        return "rerank"
    return "language"


def family_of(name: str, families: Mapping[str, Mapping[str, Any]]) -> str | None:
    for key, family in families.items():
        if matches_any(name, family["match"]):
            return key
    return None


def matches_any(name: str, patterns: Iterable[str]) -> bool:
    return any(re.search(p, name) for p in patterns)
