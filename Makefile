
all: format

.PHONY: clean format

clean:
	rm -rf .venv .*_cache __pycache__
	rm -rf build

.venv/init:
	python3 -m venv .venv
	.venv/bin/pip install -U pip setuptools wheel
	.venv/bin/pip install -e .[dev,test]
	touch ./.venv/init

format: .venv/init
	.venv/bin/rst_formatter --check testfile.rst

test: .venv/init
	(. .venv/bin/activate && pytest .)

