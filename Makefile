# OpenCode Telegram bot - common tasks.
# Run `make` or `make help` to list targets.

PY      := .venv/bin/python
PIP     := .venv/bin/pip
SERVICE := opencode-telegram.service

.PHONY: help install run service-start service-stop service-restart service-status logs clean

help:
	@echo "make install          Install / refresh dependencies into .venv"
	@echo "make run              Run the bot in the foreground"
	@echo "make service-start    Start the systemd user service"
	@echo "make service-stop     Stop the systemd user service"
	@echo "make service-restart  Restart the systemd user service"
	@echo "make service-status   Show systemd user service status"
	@echo "make logs             Follow the service logs"
	@echo "make clean            Remove caches and build artifacts"

install:
	$(PIP) install -e .

run:
	$(PY) -m opencode_telegram.main

service-start:
	systemctl --user start $(SERVICE)

service-stop:
	systemctl --user stop $(SERVICE)

service-restart:
	systemctl --user restart $(SERVICE)

service-status:
	systemctl --user status $(SERVICE) --no-pager

logs:
	journalctl --user -u $(SERVICE) -f

clean:
	find . -type d -name __pycache__ -not -path './.venv/*' -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache src/opencode_telegram.egg-info
