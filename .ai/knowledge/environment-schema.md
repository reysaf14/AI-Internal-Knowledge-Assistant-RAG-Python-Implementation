# Environment Schema — Internal Knowledge Assistant

- Schema version: `1.5`
- Date: `2026-10-11`
- Status: `APPROVED`
- Approved by: `Human` on `2026-10-11`
- Canonical runtime template: root `.env.example`
- Real credential values must never be recorded in this schema.

| Name | Purpose / type | Required / condition | Environment | Safe example | Owner / source | Secret? | Consumer / validation |
|---|---|---|---|---|---|---|---|
| `APP_ENV` | Application profile enum | Required | `local`, `test`, `container` | `container` | Engineer / selected launcher | No | Entrypoint; rejects unsupported profiles |
| `RAG_IMAGE` | Prebuilt image reference used by Compose | Optional; default is `rag-assistant:local` | Compose host only | `rag-assistant:local` | Operator selects an approved tag or digest | No | Compose image selector; Compose does not build or publish the image |
| `DOCS_PATH` | Approved corpus root, relative to the application root | Required for ingest | `local`, `test`, `container` | `docs` | Human/manager ratifies corpus; Engineer validates boundary | No | Ingest; resolved path must remain below the approved `docs/` directory |
| `INDEX_PATH` | SQLite index and technical runtime-state path | Required | `local`, `test`, `container` | `.runtime/index.sqlite3` | Engineer / runtime profile | No | Ingest and bot; must remain below `.runtime/`; test uses isolated state |
| `TELEGRAM_BOT_TOKEN` | Telegram bot credential | Required for bot; not needed for ingest | `local`, `test`, `container` | Empty for documentation: `TELEGRAM_BOT_TOKEN=` | Human provisions through an approved runtime secret path | Yes | Telegram client; presence checked before network access; never logged |
| `TELEGRAM_POLL_TIMEOUT_SECONDS` | Long-poll request duration | Optional | `local`, `test`, `container` | `30` | Engineer / Telegram runtime profile | No | Polling loop; positive number; not itself the REQ-006 SLA |
| `TELEGRAM_REQUEST_TIMEOUT_SECONDS` | Timeout for Telegram calls other than long polling | Required for bot | `local`, `test`, `container` | `4` | Architect/Engineer; calibrated against REQ-006 | No | Telegram client; positive number |
| `LLM_BASE_URL` | OpenAI-compatible model endpoint | Required for bot | `local`, `test`, `container` | `https://api.deepseek.com` | DeepSeek default approved by Human; Engineer maintains adapter | No | Model adapter; must be reachable from the selected runtime |
| `LLM_API_KEY` | Credential for the DeepSeek API | Required when `LLM_BASE_URL` host is `api.deepseek.com`; optional for other endpoints | `local`, `test`, `container` | Empty in template: `LLM_API_KEY=` | Human enters the key in the ignored root `.env` | Yes | Fail-fast before model/network access; never logged, committed, or baked into an image |
| `LLM_MODEL` | Model identifier | Required for bot | `local`, `test`, `container` | `deepseek-flash` | DeepSeek default; Human may change only through an approved configuration update | No | Model adapter; cannot be empty or a placeholder when the bot runs |
| `LLM_TIMEOUT_SECONDS` | Answer-generation timeout | Required for bot | `local`, `test`, `container` | `30` | Architect/Engineer; must account for cold model loading (ADR-004) | No | Model adapter; positive number. A timeout currently returns the standard unsupported-answer text and is not fail-closed; REQ-006 measures delivered latency separately |
| `RAG_CONTEXT_LIMIT` | Number of retrieved chunks passed to the answer model | Optional; application default is `5` | `local`, `test`, `container` | `5` | Engineer/Architect; see ADR-002 | No | Retrieval policy; positive integer. Does not expose or change the frozen support-gate thresholds |
| `MAX_QUESTION_CHARS` | Maximum question length | Optional | `local`, `test`, `container` | `2000` | Architect/Engineer | No | Update validator; positive integer; oversized input is rejected before model access |
| `LOG_LEVEL` | Application logging level | Optional; default is `info` | `local`, `test`, `container` | `info` | Engineer / application default | No | Logger; validated enum and must not disable redaction |
| `TELEGRAM_ECHO_BOT_TOKEN` | Sandbox-only token for host-side Telegram E2E harness | Optional; never required by the application container | Host-side test harness only | Empty | Human provisions only for an approved sandbox run | Yes | Harness only; Compose intentionally does not pass it to the application container |

## Runtime profiles and configuration precedence

The Docker image contains the Python runtime, locked dependencies, application
source, and the approved 26-document corpus. The corpus and derived image
assets are classified Confidential. Distribute images only through a
Human-approved private route. Never provide credentials through build
arguments, build context files, image layers, or logs.

The runtime index and minimal polling/idempotency state live in the persistent
Docker named volume mounted at `/app/.runtime`. DeepSeek is an external runtime
dependency. The bot sends the current question and minimum retrieved context
to DeepSeek for supported questions; the application does not persist those
contents. Provider-side processing/retention has not been independently
verified. The bot uses outbound Telegram and model calls; Compose publishes no
inbound ports.

| Profile | Launcher / working directory | Configuration source | Data and trust boundary | Missing-value behavior |
|---|---|---|---|---|
| `local` | Python entrypoint from the project root | Process environment takes precedence over the explicitly loaded root `.env` | Approved `docs/`, local SQLite state, reachable model endpoint, Human-provisioned Telegram bot | Missing required values stop before network access or writes |
| `test` | Isolated test command | Explicit process environment or explicitly selected test config; never falls back to root `.env` | Synthetic fixtures, isolated SQLite state, mocks or approved sandbox credentials | Live targets and production corpus/credentials are rejected |
| `container` | Compose starts the prebuilt image in `/app` | Compose interpolates an operator-selected env file, then passes only the explicit allowlist in `compose.yaml`; application does not load an image `.env` | Read-only image filesystem; approved corpus in image; writable `/app/.runtime` named volume; external model and Telegram endpoints | Missing required values stop the process before polling or model calls |

For Compose commands, use `docker compose --env-file .env ...`. Shell variables
override values in the selected Compose env file; the Compose file's explicit
environment entries are the only values passed to the container. Never print
the resolved configuration. Do not pass `TELEGRAM_ECHO_BOT_TOKEN` to the
service.

The root `.env.example` is the only canonical template. Real `.env`,
`.env.test`, backups, credential exports, and key files must not enter Git or
the Docker build context. The local CLI loader accepts simple `KEY=VALUE`
assignments only, does not interpolate or execute commands, and does not
overwrite existing process environment values.

## Credential references

The application has no n8n credential store. The runtime credentials are
`TELEGRAM_BOT_TOKEN` and, for the default DeepSeek endpoint, `LLM_API_KEY`.
Human enters them through the approved runtime path. Their values are not
needed for design, synthetic implementation, or reports.

## Validation and verification

- Configuration errors identify the variable or path category, never its value.
- Validation commands must not print environment values.
- A valid configuration is not evidence that Telegram delivery or model
  generation succeeded.
- QA must verify that tests do not fall back to `.env`, live endpoints,
  production corpus, or live credentials.
- Docker image-build and runtime evidence must record the artifact identity
  without disclosing credentials or corpus contents.

## Revision history

| Version | Date | Change | Approval |
|---|---|---|---|
| `1.4` | `2026-10-11` | Replaces the host-specific VPS profile with `container`; documents the Compose allowlist, named-volume state, private image boundary, and runtime-only credentials | Human |
| `1.5` | `2026-10-11` | Selects DeepSeek as the default API runtime; makes its key required at startup, documents minimum query/context egress, and leaves the key blank in the template | Human |
