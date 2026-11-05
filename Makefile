# make catalog | brand | build [P=<platform>] | test | check
PY ?= python3
P ?= all
BASE_URL ?=

catalog:
	$(PY) catalog/build_catalog.py

brand:
	$(PY) brand/build_brand.py

build:
	$(PY) tools/build.py $(P) $(if $(BASE_URL),--base-url $(BASE_URL))

test:
	$(PY) -m pytest tests -q

# Tests import from dist/ and leave __pycache__ there, so build again before checking the packages.
check: test build
	$(PY) tools/check.py

.PHONY: catalog brand build test check
