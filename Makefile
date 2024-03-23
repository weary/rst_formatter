
all: .venv/init

.PHONY: clean format

clean:
	rm -rf .venv .*_cache __pycache__
	rm -rf build

.venv/init:
	python3 -m venv .venv
	.venv/bin/pip install -U pip setuptools wheel
	.venv/bin/pip install docutils lxml lxml-stubs rst2pdf
	.venv/bin/pip install rstcheck mypy ruff typeguard pytest
	.venv/bin/pip install ipdb
	touch ./.venv/init

format: .venv/init
	.venv/bin/python rst_formatter.py

test: .venv/init
	.venv/bin/pytest .

