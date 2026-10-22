.PHONY: check lint test token ingest uploader health aggregate install-local uninstall-local
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

install-local:
	python3 -m telemetry.launchd install

uninstall-local:
	python3 -m telemetry.launchd uninstall
