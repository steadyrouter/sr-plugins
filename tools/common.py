"""Shared helpers for the platform builders."""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, replace
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"


class _Dumper(yaml.SafeDumper):
    def ignore_aliases(self, data):  # no &anchors in generated files
        return True


def dump_yaml(data) -> str:
    return yaml.dump(data, Dumper=_Dumper, allow_unicode=True, sort_keys=False, width=1000)


def load_yaml(path: Path):
    return yaml.safe_load(path.read_text())


@dataclass
class Context:
    site: dict
    catalog: dict
    strings: dict
    versions: dict
    families: dict
    video: dict
    api_base: str

    def models(self, category: str, *, platform: str | None = None) -> list[dict]:
        return [m for m in self.catalog["models"]
                if m["category"] == category and (platform is None or platform not in m.get("exclude", []))]

    def for_channel(self, channel: str) -> "Context":
        """This context with get_key_url set to one plugin's sign-up link."""
        url = f"{self.site['sign_up_url']}?aff={self.site['channel_codes'][channel]}"
        return replace(self, site={**self.site, "get_key_url": url})


def load_context(base_url: str | None = None) -> Context:
    site = load_yaml(ROOT / "catalog" / "site.yaml")
    return Context(
        site=site,
        catalog=json.loads((ROOT / "catalog" / "catalog.json").read_text()),
        strings=load_yaml(ROOT / "i18n" / "strings.yaml"),
        versions=load_yaml(ROOT / "catalog" / "versions.yaml"),
        families=load_yaml(ROOT / "catalog" / "families.yaml"),
        video=load_yaml(ROOT / "catalog" / "video-params.yaml"),
        api_base=(base_url or site["api_base"]).rstrip("/"),
    )


def safe_file_name(model: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", model)


def fresh_dir(path: Path) -> Path:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)
    return path


def copy_tree(src: Path, dst: Path) -> None:
    shutil.copytree(src, dst, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))


def fill(text: str, ctx: Context) -> str:
    """Replace {{site_key}} with the value from site.yaml."""
    return re.sub(r"\{\{(\w+)\}\}", lambda m: str(ctx.site[m.group(1)]), text)
