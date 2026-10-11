# AI Internal Knowledge Assistant (RAG) — Docker Runtime

Internal knowledge assistant for Toko Makmur Jaya. The application indexes the
26 approved Markdown documents in `docs/`, retrieves grounded context, answers
through an OpenAI-compatible local model endpoint, and can deliver responses
through a Telegram polling boundary.

M0–M6 implementation evidence predates the 2026-10-10 English corpus
migration. The migrated local index contains `26 files` and `433 chunks`, but
post-migration M5 remains `NOT_VERIFIED`; the older Telegram-sandbox result is
historical. Docker packaging is the active Engineer task under approved PRD
`1.2` and Architecture `1.2`. A successful image build is implementer
evidence only and does not replace M5, independent QA, Security review, or
Human release approval.

## Prerequisites

- Docker Engine with Docker Compose v2, running on the operator host.
- The repository root as the working directory for build and Compose commands.
- The approved corpus: exactly 26 Markdown files named `00_*.md` through
  `25_*.md`; the files are included in the image.
- A model endpoint reachable from the container. For a host service, configure
  `LLM_BASE_URL` with `host.docker.internal` and the service's listening port.
- A Human-provisioned Telegram bot token for bot startup. Ingestion does not
  require the token.

## Build and configure

From PowerShell at the repository root:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

Edit the ignored `.env` file. Set `LLM_BASE_URL` to an endpoint the container
can reach, replace `local-default` with the concrete model identifier, and
provide `TELEGRAM_BOT_TOKEN` for live bot use. Keep `LLM_API_KEY` empty unless
the selected endpoint requires authentication. Compose passes only the
application variables declared in `compose.yaml`; the sandbox echo-bot token
is not passed to the container.

Build a versioned runtime image once:

```powershell
docker build --tag rag-assistant:2026-10-11 .
```

Set `RAG_IMAGE=rag-assistant:2026-10-11` in `.env` so Compose uses that image.
Build context excludes `.env*`, `.runtime/`, Git metadata, local environments,
and test/evaluation files. The image contains the approved corpus, so the image
and any exported image archive are `Confidential`; distribute them only via a
Human-approved private route. Do not pass credentials as build arguments or
bake them into the image.

`LLM_TIMEOUT_SECONDS` defaults to `30` (ADR-004). It is a **ceiling, not a
target**: an idle local model may unload and its next request may pay a cold
load of roughly 26 seconds on the reference machine. Warm answers cost about
1–4 seconds. A timeout currently returns the same user-facing line as a normal
abstention, so it is not distinguishable to the asker; the fallback does not
fail closed. The `<5.0 seconds` REQ-006 limit remains unchanged.

## Operator commands

All commands use the repository root as the current directory and the same
`.env` file. Do not print the rendered Compose configuration.

### Validate configuration before side effects

```powershell
docker compose --env-file .env config --quiet
docker compose --env-file .env run --rm --no-deps rag-assistant validate ingest
```

The first command checks Compose syntax without rendering values. The second
checks the container profile, packaged `docs/` boundary, `.runtime/` volume
boundary, and safe logging configuration. It performs no rebuild and no
network call.

After an index exists, validate bot readiness without contacting Telegram:

```powershell
docker compose --env-file .env run --rm --no-deps rag-assistant validate bot
```

The bot validation requires a non-empty `TELEGRAM_BOT_TOKEN` and an active
index. A missing token fails with exit code `3` before network use.

### Build or replace the knowledge index

```powershell
docker compose --env-file .env run --rm --no-deps rag-assistant ingest
```

The command validates the corpus, parses and chunks all 26 files, builds a new
SQLite/FTS5 index, verifies its counts, and atomically activates it. A failed
rebuild does not activate a partial index. The generated index and polling
state live in the named `rag_runtime` volume, outside the disposable container
filesystem. The same image and corpus produce the same corpus version.

### Start the live bot

```powershell
docker compose --env-file .env up -d rag-assistant
docker compose --env-file .env logs --follow rag-assistant
```

The bot requires a valid active index, a model endpoint reachable from the
container, and a Telegram token injected through the approved runtime path.
The service publishes no inbound ports. It runs as UID/GID `10001`, uses a
read-only root filesystem with dropped Linux capabilities, and can write only
to the `rag_runtime` volume mounted at `/app/.runtime`. The lock prevents a
second instance sharing that volume. Exit code `4` means another instance
owns the lock.

Stop the service while retaining the volume with
`docker compose --env-file .env stop rag-assistant`. `docker compose down`
without `-v` also retains it. Do not use `down -v` unless deleting the index
and polling state is intended.

To promote the same artifact, transfer the approved image through a private
registry or a controlled `docker save` / `docker load` handoff. Keep the same
image digest on every compatible Docker host and provide each environment's
configuration at runtime. This project does not publish an image to a registry
or authorize a deployment target.

For an approved corpus update, build a new tagged image containing the new
documents, stop the bot, point `RAG_IMAGE` at that tag, run `ingest` using the
new image and existing volume, then start the service again. The builder
activates a replacement index atomically and leaves the old active index in
place if rebuilding fails.

## Known limitations

These are documented boundaries. Changes to retrieval, authorization, or
runtime behavior require an updated decision in `.ai/decisions/`.

- **Wording, not meaning, is matched.** Retrieval requires every search term of
  a question to appear in a document; the support gate is lexical and the
  approved architecture excludes vector search by name. A question phrased in
  the corpus vocabulary is answered when it uses the same terms as the source:
  *"What are the store operating hours?"* can be answered from a matching
  document. A synonym-based or inflected question may abstain because the
  lexical support gate does not perform semantic expansion.
- **Consequence for reading an abstention.** An abstention does **not** mean the
  corpus lacks the answer. It may mean the question used different words. If a
  reasonable question abstains, try rephrasing it with the vocabulary the
  documents use before concluding the answer is missing (ADR-004).
- **No typo correction and no stemming.** Misspellings and inflected forms
  (`leaves`, `leave2`) are not recognised.
- **The bot answers any chat that reaches it.** The runtime does not restrict
  which chat it replies in, so anyone who finds the bot can query internal
  policy. An allowlist is recommended before this runs beyond a test machine,
  and is tracked as a separate decision (ADR-004, "not fixed").

### Run the source self-tests

```powershell
uv run --group dev pytest tests
uv run --group dev ruff check src tests
uv run python -m compileall -q src tests
```

These developer commands run outside the runtime image. Tests use synthetic
fixtures and local boundaries. They do not prove Telegram network delivery,
production credentials, Docker runtime behavior, or the approved M5 12+3
evaluation.

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

- `/app/docs` in the image is the approved corpus boundary; do not add operator
  guides or arbitrary Markdown files there because ingestion expects exactly
  26 files.
- Docker named volume `rag_runtime`, mounted at `/app/.runtime`, holds the
  active SQLite index, technical polling/idempotency state, and single-instance
  lock. It is not a conversation transcript.
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

The Docker image has not yet been built or exercised in this work session.
Post-migration M5 remains `NOT_VERIFIED`; the pre-migration Telegram sandbox
result is historical. Independent QA, Security, and Human release approval
remain separate gates. M7 covers Docker packaging and a portable runtime; it
does not include VPS readiness or deployment.
