# Architecture Addendum — DeepSeek Runtime

- Date: `2026-10-11`
- Status: `APPROVED` under ADR-006
- Applies to: Architecture `1.2`; proposed next consolidated version `1.3`
- Related PRD: `1.3`; Environment Schema: `1.5`

The canonical Architecture file could not be updated by the workspace patch
tool during this migration (`path contains a reparse point`). This addendum is
the persisted provider-specific design evidence; merge it into Architecture
§1, §2.2, §2.4, §6, §7, §8.1, and §9 when that file becomes writable. Until
then, the registry must continue to identify the canonical Architecture as
version `1.2` and call out this addendum. Do not claim its version was bumped.

## Runtime and trust boundary

- Default provider: DeepSeek API at `https://api.deepseek.com`, model
  `deepseek-flash`, using `/chat/completions`.
- The runtime injects `LLM_API_KEY`; the value is required for this host and
  fail-fast validation occurs before model/network access. It is never logged,
  stored in source, passed as a build argument, or baked into the image.
- For supported questions, only the current question and minimum retrieved
  chunks are sent. No history or full corpus is sent. Direct identities,
  individual records, credentials, and production payloads remain blocked.
- The Human approved this external data boundary on `2026-10-11`. The
  application does not persist conversation content; provider-side processing
  and retention remain unverified.
- Every DeepSeek request explicitly sends
  `thinking: {"type":"disabled"}`. Ollama's native `think: false` path
  remains available for non-default local use. Ollama-only prewarm scripts
  skip remote providers.

## Acceptance additions

| ID | Requirement | Scenario and expected result | Verification |
|---|---|---|---|
| `AC-042 / REQ-003, REQ-007` | DeepSeek request contract | Synthetic request targets `/chat/completions`, uses Bearer auth, disables thinking, and sends only current question plus selected context; no key/prompt logging | Unit + mock HTTP integration; required |
| `AC-043 / REQ-007` | Missing provider credential | DeepSeek selected with no key exits `3` before an external request; diagnostic names `LLM_API_KEY` without a value | Unit + local startup validation; required |

These synthetic criteria do not prove provider authentication, model quality,
latency, provider retention behavior, or Telegram delivery. M5 remains
`NOT_VERIFIED` until the approved 12+3 evaluation and separate Telegram
sandbox criteria are satisfied.
