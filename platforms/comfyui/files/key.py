"""Where the API key comes from. It is never a node input, so it cannot travel inside a shared workflow or image."""

from __future__ import annotations

import json
import os
from pathlib import Path

ENV = "STEADYROUTER_API_KEY"
SETTING = "SteadyRouter.ApiKey"  # registered by web/steadyrouter.js


def settings_file() -> Path | None:
    """The settings ComfyUI keeps for its single user. With --multi-user there is no way to tell whose run this is."""
    import folder_paths
    from comfy.cli_args import args

    if args.multi_user:
        return None
    return Path(folder_paths.get_user_directory()) / "default" / "comfy.settings.json"


def api_key() -> str:
    """The environment variable first, then the key saved in ComfyUI's settings. Empty if neither is set."""
    key = os.environ.get(ENV, "").strip()
    if key:
        return key
    path = settings_file()
    if path is None:
        return ""
    try:
        value = json.loads(path.read_text(encoding="utf-8")).get(SETTING)
    except (OSError, ValueError, AttributeError):
        return ""
    return value.strip() if isinstance(value, str) else ""
