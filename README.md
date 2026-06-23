# AI-Powered Telegram Bot Builder Platform

This project runs two independent Telegram services:

- `builder_bot.py`: the Telegram-only management bot for creating, importing, editing, enabling, disabling, exporting, and inspecting bots.
- `runtime_engine.py`: the shared Runtime Engine that hot-loads every enabled user bot from SQLite and executes only JSON schema steps through approved plugins.

The platform never generates or executes Python code for user bots.

## Ubuntu Install

```bash
sudo adduser --system --group --home /opt/telegram-ai-bot-builder botbuilder
sudo mkdir -p /opt/telegram-ai-bot-builder
sudo chown botbuilder:botbuilder /opt/telegram-ai-bot-builder
sudo -u botbuilder git clone <repo-url> /opt/telegram-ai-bot-builder
cd /opt/telegram-ai-bot-builder
sudo -u botbuilder python3.12 -m venv .venv
sudo -u botbuilder .venv/bin/pip install -e .
sudo -u botbuilder cp .env.sample .env
sudo -u botbuilder nano .env
sudo cp systemd/botbuilder.service /etc/systemd/system/
sudo cp systemd/runtimeengine.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now botbuilder runtimeengine
```

Required environment variables:

- `BUILDER_BOT_TOKEN`
- `TELEGRAM_API_ID`
- `TELEGRAM_API_HASH`
- `DATABASE_PATH`
- `GEMINI_API_KEY`

## Builder Commands

```text
/start
/createbot <name>|<token>|<prompt>
/editbot <bot_id>|<instruction>
/deletebot <bot_id>
/mybots
/viewschema <bot_id>
/enable <bot_id>
/disable <bot_id>
/analytics <bot_id>
/exportschema <bot_id>
/importschema <name>|<token>|<json>
```

## Runtime Model

`runtime_engine.py` polls SQLite, starts newly enabled bots, stops disabled bots, and restarts modified bots. Every bot receives a persistent Kurigram session under `sessions/`.

Schemas are validated before storage and again before runtime execution. Step execution is restricted to the plugin registry.

## Examples

See:

- `examples/support_bot.json`
- `examples/lead_capture_bot.json`
- `examples/faq_bot.json`

## Custom Plugins

Create a Python module in `plugins/` and expose a `plugin` object with `name`, `version`, `config_schema`, and `execute()`. See `plugins/example_custom.py`.
