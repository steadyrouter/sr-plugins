import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("build_brand", ROOT / "brand" / "build_brand.py")
brand = importlib.util.module_from_spec(spec)
spec.loader.exec_module(brand)


def test_mono_is_current_color_without_background():
    out = brand.mono((ROOT / "brand" / "logo.svg").read_text())
    assert "currentColor" in out and "<rect" not in out and "#" not in out
