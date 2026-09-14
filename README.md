# AI Internal Knowledge Assistant (RAG)

Internal knowledge assistant for Toko Makmur Jaya. The application indexes the
26 approved Markdown documents in `docs/`, retrieves grounded context, answers
through an OpenAI-compatible local model endpoint, and can deliver responses
through a Telegram polling boundary.

M5 remains `NOT_VERIFIED`: the approved 12+3 evaluation and local Qwen runtime
were not available. This guide documents the reproducible local operator path;
it does not replace the M5 or independent QA/Security gates.

## Prerequisites

- Python `3.12.*` (the project virtual environment is verified with 3.12.13).
- `uv` for dependency/environment management.
- The repository root as the working directory.
- The approved corpus: exactly 26 files named `00_*.md` through `25_*.md`.
- A local OpenAI-compatible model endpoint for live bot use. The current
  decision is Qwen 8B served locally; no external router is required.
- A Telegram bot token only for live Telegram use. It is not required for
  ingestion, tests, or mock-boundary checks.

## Setup

From PowerShell at the repository root:

```powershell
uv sync --dev
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

Edit `.env` only through the approved local runtime path. The CLI explicitly
loads `.env` for `APP_ENV=local`; process/injected environment values always
override file values. Test and VPS profiles do not implicitly load `.env`.

Canonical model variables are `LLM_BASE_URL`, `LLM_MODEL`,
`LLM_TIMEOUT_SECONDS`, and optional `LLM_API_KEY`. For a local Qwen endpoint,
replace the safe example `local-default` with the concrete served model name;
keep `LLM_API_KEY` empty unless the endpoint explicitly requires auth.

Never commit `.env`, a token, an API key, a production payload, or a runtime
database. The application does not print credential values.

## Operator commands

All commands use the project root as the current directory.

### Validate configuration before side effects

```powershell
uv run python -m rag_assistant validate ingest
```

This checks the local profile, the `docs/` boundary, the `.runtime/` index
boundary, and safe logging configuration. It performs no rebuild and no
network call.

After an index exists, validate bot readiness without contacting Telegram:

```powershell
uv run python -m rag_assistant validate bot
```

The bot validation requires a non-empty `TELEGRAM_BOT_TOKEN` and an active
index. A missing token fails with exit code `3` before network use.

### Build or replace the knowledge index

```powershell
uv run python -m rag_assistant ingest
```

The command validates the corpus, parses and chunks all 26 files, builds a new
SQLite/FTS5 index, verifies its counts, and atomically activates it. A failed
rebuild does not activate a partial index. Repeat the command after an
approved document replacement; the same corpus produces the same corpus
version.

### Start the live bot

```powershell
uv run python -m rag_assistant bot
```

The bot requires a valid active index, a local model endpoint, and a Telegram
token injected through the approved secret path. It uses `.runtime/bot.lock`
to prevent two polling instances. Exit code `4` means another instance owns
the lock.

### Run the self-tests

```powershell
uv run --group dev pytest tests
uv run --group dev ruff check src tests
uv run python -m compileall -q src tests
```

Tests use synthetic fixtures and local boundaries. They do not prove Telegram
network delivery, production credentials, or the approved M5 12+3 evaluation.

## Runtime files and corpus replacement

- `docs/` is the approved corpus boundary; do not add operator guides or
  arbitrary Markdown files there because ingestion expects exactly 26 files.
- `.runtime/index.sqlite3` is the active derived index.
- `.runtime/bot_state.sqlite3` contains technical polling/idempotency state
  only; it is not a conversation transcript.
- `.runtime/bot.lock` marks the single active bot instance.
- If a rebuild fails, stop and inspect the sanitized error. Do not manually
  edit SQLite files or delete the active index to force a rebuild.

## Exit codes and failure handling

| Code | Meaning |
|---:|---|
| `0` | Command completed successfully |
| `1` | Rebuild failure or unexpected top-level failure |
| `3` | Invalid/missing configuration or path boundary |
| `4` | Another bot instance already holds the runtime lock |

Configuration diagnostics name the invalid variable or path category but never
print its value. Network/provider errors are handled by the M3/M4 failure
controls and must not be interpreted as a successful answer.

## Current verification boundary

M0–M4 evidence remains implementer-level and M5 is still `NOT_VERIFIED`.
Telegram sandbox credentials, the approved M5 dataset/rubric, and the local
Qwen runtime are intentionally not required for this packaging milestone.
Independent QA, Security, and release approval remain separate gates.
