#!/usr/bin/env python3
"""Run the fake gateway on its own, for testing a real Dify install. usage: serve_fake.py <public base url>"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fake_upstream import Fake  # noqa: E402

fake = Fake("0.0.0.0", 9000, sys.argv[1])
print("fake gateway on :9000", flush=True)
while True:
    time.sleep(3600)
