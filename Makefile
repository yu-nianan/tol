.PHONY: install run lint test smoke check fmt

PY ?= python

install:
	$(PY) -m pip install -r requirements.txt

run:
	$(PY) -m uvicorn app.main:app --reload --port 8000

fmt:
	$(PY) -m ruff format .

lint:
	$(PY) -m ruff check .

test:
	$(PY) -m pytest

smoke:
	$(PY) scripts/smoke.py

check: lint test
	@echo "lint + test 通过；smoke 需先启动服务"
