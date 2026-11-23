PY := .venv/bin/python
PIP := .venv/bin/pip
TARGET ?= duckdb

.PHONY: setup test serve run demo slack-dry-run bench screenshots check-workflow clean

setup:
	python3 -m venv .venv
	$(PIP) install -q -r requirements.txt
	@test -f .env || cp .env.example .env
	@echo "setup done. Start the mock sources with 'make serve', then 'make run'."

test:
	$(PY) -m pytest -q

serve:
	$(PY) -m mock_sources

# extract -> load -> transform -> test -> report, against whatever SHOPIFY_BASE_URL / STRIPE_BASE_URL point at
run:
	$(PY) -m pipeline all --target $(TARGET)

# one command, no second terminal: start the mock sources, run the pipeline, print the Slack payload
demo:
	@$(PY) scripts/demo.py

slack-dry-run:
	$(PY) -m pipeline slack --dry-run

bench:
	$(PY) scripts/benchmark.py

screenshots:
	node scripts/screenshots.js

# needs n8n installed and the mock sources running (make serve); see the script header
check-workflow:
	$(PY) scripts/check_workflow.py

clean:
	rm -rf data reports/*.html reports/*.json dbt_project/target dbt_project/logs
