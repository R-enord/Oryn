.PHONY: install check lint test run doctor

install:            ## dev install (venv recommended)
	pip install -e ".[dev]"

check: lint test    ## what CI runs

lint:
	ruff check radar tests

test:
	pytest -q

run:                ## run the service locally, printing instead of sending
	python -m radar run --dry-run

doctor:             ## live-test every source
	python -m radar sources doctor
