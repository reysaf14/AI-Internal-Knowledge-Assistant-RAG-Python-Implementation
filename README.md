# AI Internal Knowledge Assistant (RAG)

Internal knowledge assistant for Toko Makmur Jaya. The application indexes the
26 approved Markdown documents in `docs/`, retrieves grounded context, answers
through an OpenAI-compatible local model endpoint, and can deliver responses
through a Telegram polling boundary.

M0–M6 are implemented and self-tested, and M5 is verified at the
`telegram-sandbox` level over the full approved 12+3 set (`content` 12/15,
`sources` 12/12, `abstention` 3/3, `latency` 15/15). This guide documents the
reproducible local operator path; it does not replace independent QA or
Security review, which remain separate gates.

## Prerequisites

- Python `3.12.*` (the project virtual environment is verified with 3.12.13).
- `uv` for dependency/environment management.
- The repository root as the working directory.
- The approved corpus: exactly 26 files named `00_*.md` through `25_*.md`.
- A local Ollama model endpoint for live bot use. The current local run uses
  `gemma4:e2b-it-qat`; no external router is required.
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
`LLM_TIMEOUT_SECONDS`, and optional `LLM_API_KEY`.

`LLM_TIMEOUT_SECONDS` defaults to `30` (ADR-004). It is a **ceiling, not a
target**: a local model endpoint unloads an idle model, and the next request
pays a one-off cold load of roughly 26 s on the reference machine. At the
earlier default of 3 s such a request always timed out, and a timeout is
reported with the same fixed line as a normal abstention, so it was
indistinguishable to the person asking. Warm answers cost about 1–4 s and are
unaffected. Note that a timeout does **not** fail closed: the fallback text is
sent as a successful response with no sources. For the local Ollama endpoint
at `http://127.0.0.1:11434/v1`, replace the safe example `local-default` with
the concrete served model name; keep `LLM_API_KEY` empty unless the endpoint
explicitly requires auth. The application selects Ollama's native `/api/chat`
path and sends `think=false` for this local endpoint.

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

## Known limitations

These are accepted boundaries, not bugs to be fixed silently. Changing any of
them means changing an approved artefact, so it needs a Human decision first
(see `.ai/decisions/`).

- **Wording, not meaning, is matched.** Retrieval requires every search term of
  a question to appear in a document; the support gate is lexical and the
  approved architecture excludes vector search by name. A question phrased in
  the corpus's own vocabulary is answered even when it is a full paraphrase:
  *"toko ini tutup jam berapa?"* is answered correctly from a different
  document than the one *"Jam berapa toko Makmur Jaya tutup?"* uses. A question
  that swaps a word is not: *"kapan tokonya tutup?"* abstains, because `tokonya`
  is `toko` plus a suffix (and `toko` is itself a stopword), and
  *"berapa jatah cuti setahun?"* abstains because `jatah`/`setahun` are
  synonyms of `hari`/`tahunan`.
- **Consequence for reading an abstention.** An abstention does **not** mean the
  corpus lacks the answer. It may mean the question used different words. If a
  reasonable question abstains, try rephrasing it with the vocabulary the
  documents use before concluding the answer is missing (ADR-004).
- **No typo correction and no stemming.** Misspellings and inflected forms
  (`cutinya`, `cuti2`) are not recognised.
- **The bot answers any chat that reaches it.** The runtime does not restrict
  which chat it replies in, so anyone who finds the bot can query internal
  policy. An allowlist is recommended before this runs beyond a test machine,
  and is tracked as a separate decision (ADR-004, "not fixed").

### Run the self-tests

```powershell
uv run --group dev pytest tests
uv run --group dev ruff check src tests
uv run python -m compileall -q src tests
```

Tests use synthetic fixtures and local boundaries. They do not prove Telegram
network delivery, production credentials, or the approved M5 12+3 evaluation.

### Run the local CSV evaluation

```powershell
.venv\Scripts\python.exe scripts\run_local_csv_eval.py
```

The command keeps the answer key in memory, emits sanitized metrics only, and
uses a temporary technical state directory. It reads `RAG_CONTEXT_LIMIT` and
prints the effective `context_limit` it ran at. The local runner reports
`acceptance_verdict=NOT_VERIFIED` by design: the targets are checked locally,
but only `telegram-sandbox` execution can lift the verification level.

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

M0–M6 evidence is implementer-level self-test. M5 additionally has
`telegram-sandbox` evidence over the full approved 12+3 set via the live
Telegram boundary. Both are still **self-reported**: the architecture states
that an architecture pass is not a security pass, and that a milestone result is
not by itself independent QA. Independent QA, Security, and release approval
remain separate gates, as does VPS readiness.
