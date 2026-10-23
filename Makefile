.PHONY: up down check lint test token ingest uploader health aggregate dashboard install-local uninstall-local
RUN = /tmp/claude-telemetry

up: down
	mkdir -p $(RUN)
	nohup python3 -m telemetry.fake_ingest > $(RUN)/ingest.log 2>&1 & echo $$! > $(RUN)/ingest.pid
	nohup python3 -m telemetry.dashboard > $(RUN)/dashboard.log 2>&1 & echo $$! > $(RUN)/dashboard.pid
	TELEMETRY_ENDPOINT=http://localhost:8080/v1/events nohup python3 -m telemetry.service > $(RUN)/uploader.log 2>&1 & echo $$! > $(RUN)/uploader.pid
	@echo dashboard: http://127.0.0.1:8081/

down:
	@for file in $(RUN)/*.pid; do [ -f "$$file" ] && kill $$(cat "$$file") 2>/dev/null; rm -f "$$file"; done; sleep 1; true

check: lint test

lint:
	ruff check .

test:
	python3 -m unittest discover -p "*_test.py" -s telemetry -t .

token:
	security add-generic-password -U -s claude-telemetry -a "$$USER" -w "$$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"

ingest:
	python3 -m telemetry.fake_ingest

uploader:
	TELEMETRY_ENDPOINT=http://localhost:8080/v1/events python3 -m telemetry.service

health:
	python3 -m telemetry.service --health

aggregate:
	python3 -m telemetry.fake_ingest --aggregate

dashboard:
	python3 -m telemetry.dashboard

install-local:
	python3 -m telemetry.launchd install

uninstall-local:
	python3 -m telemetry.launchd uninstall
