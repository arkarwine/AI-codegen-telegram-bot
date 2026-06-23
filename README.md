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
sudo -u botbuilder mkdir -p sessions
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

Optional:

- `OWNER_TELEGRAM_ID`: if set, only this Telegram user can call `/runtime`.

## Builder Commands

```text
/start
/createbot
/editbot
/deletebot bot_id
/mybots
/status bot_id
/viewschema bot_id
/enable bot_id
/disable bot_id
/analytics bot_id
/exportschema bot_id
/importschema
/runtime
/cancel
```

`/createbot`, `/editbot`, and `/importschema` are step-by-step Telegram conversations. `/createbot` and `/importschema` enable the bot by default after token and schema validation. `/importschema` accepts pasted JSON or an uploaded `.json` document. Bot tokens are validated with Telegram before a bot is stored or enabled.

## Runtime Model

`runtime_engine.py` polls SQLite, starts newly enabled bots, stops disabled bots, and restarts modified bots. Every bot receives a persistent Kurigram session under `sessions/`.

Schemas are validated before storage and again before runtime execution. Step execution is restricted to the plugin registry.

The runtime writes a heartbeat snapshot to SQLite for `/runtime` and records per-bot `last_started_at`, `last_failed_at`, and `last_error` for `/status`.

## Flow Features

The Runtime Engine supports command, text, button, callback, regex, and catch-all triggers. Flows may be entered by triggers or jumped to by other steps with `next`, `next_flow`, `next_step`, `on_success`, or `on_failure`.

Steps can use `when` conditions, pause with `wait_for_input`, store session/user/global variables with `set_variable`, render values with `{{name}}`, `{{user.name}}`, `{{global.name}}`, and use event helpers such as `{{event.text}}` and `{{telegram_user.id}}`.

Supported action plugins include messages, buttons, edit/delete message, wait, conditions, scoped variables, safe key/value storage, HTTP GET, Gemini chat, scheduler, broadcast, admin-only guards, and analytics.

## Database Interactions

Schemas can use `database_query` for persistent SQLite records without raw SQL. Data is stored by `collection`, `scope`, and `key`.

Supported actions:

- `set`, `upsert`, `save`: create or replace a record with `key` and `value`
- `get`, `read`: read one record by `key`
- `delete`: delete one record by `key`
- `list`: list records in a collection, with optional `limit`
- `count`: count records in a collection
- `exists`: check whether a record exists
- `increment`: increment a numeric record by optional `amount`
- `append`: append `item` or `value` to an array record

Example:

```json
{
  "type": "database_query",
  "action": "set",
  "collection": "leads",
  "scope": "global",
  "key": "{{telegram_user.id}}",
  "value": {
    "name": "{{name}}",
    "email": "{{email}}"
  }
}
```

## Examples

See:

- `examples/support_bot.json`
- `examples/lead_capture_bot.json`
- `examples/faq_bot.json`
- `examples/advanced_flow_bot.json`
- `examples/database_lead_bot.json`

## Custom Plugins

Create a Python module in `plugins/` and expose a `plugin` object with `name`, `version`, `config_schema`, and `execute()`. See `plugins/example_custom.py`.
