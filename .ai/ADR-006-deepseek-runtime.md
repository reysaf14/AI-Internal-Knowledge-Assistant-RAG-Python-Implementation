# ADR-006 — DeepSeek API Runtime

- Status: `APPROVED`
- Date: `2026-10-11`
- Scope: PRD 1.3, Environment Schema 1.5, M3/M5/M7 runtime configuration
- Decision maker: `Human`; explicitly requested this migration on `2026-10-11`
- Supersedes: local Ollama/Gemma as the default only; Ollama remains a supported non-default adapter path.

## Context

The Human selected DeepSeek so only an API key remains to be entered. The
adapter is OpenAI-compatible. The approved corpus is Confidential, so provider
egress must be recorded as an explicit trust boundary.

## Decision

1. Use `https://api.deepseek.com` and `deepseek-flash` as the default model
   endpoint and identifier. Keep both runtime-configurable.
2. Leave `LLM_API_KEY=` blank in the template and ignored operator `.env`.
   Require a key when the endpoint host is `api.deepseek.com` and fail with
   exit code `3` before model access. Never log, print, commit, pass as a build
   argument, or bake the key into an image.
3. Send only the current question and the minimum retrieved chunks required
   for a supported answer. Do not send conversation history or the full
   corpus. Direct identities, individual records, credentials, and production
   payloads remain blocked.
4. The Human approved this external data boundary in the request dated
   `2026-10-11`. This does not claim that the provider does not retain or
   process requests; provider-side processing and retention are unverified.
5. Send `thinking: {"type":"disabled"}` to DeepSeek. Keep native Ollama's
   existing `think: false` behavior and do not send the DeepSeek option to
   unrelated OpenAI-compatible endpoints.
6. Do not make a live DeepSeek request until the Human provisions the key.
   Use synthetic HTTP stubs for adapter verification.

## Consequences

- Model-backed runtime requires outbound internet and a Human-provisioned API
  key. Docker image build and corpus ingestion remain offline.
- Application non-persistence does not imply provider non-retention.
- Provider/model content and latency evidence must be rerun. M5 remains
  `NOT_VERIFIED` until the approved 12+3 run and separate Telegram sandbox
  delivery evidence are complete.
- Ollama-specific prewarm scripts must skip remote API providers.
- DeepSeek quality, `<5.0 seconds` delivery, provider authentication, and
  provider data handling have not been live-verified.

## Acceptance linkage

Architecture acceptance rows `AC-042` and `AC-043` cover the synthetic HTTP
request contract and fail-fast behavior. They do not prove provider
authentication, model quality, latency, provider data handling, or Telegram
delivery.

## References

- DeepSeek OpenAI-compatible API guide: <https://api-docs.deepseek.com/guides/codex>
- DeepSeek chat-completions API: <https://api-docs.deepseek.com/api/create-chat-completion/>
