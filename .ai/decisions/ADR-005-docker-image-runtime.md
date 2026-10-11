# ADR-005 — Docker Image and Portable Runtime

- Status: `APPROVED`
- Date: `2026-10-11`
- Scope: PRD `1.2`, Architecture `1.2`, M7
- Decision maker: `Human`; explicitly approved in the project conversation on `2026-10-11`
- Supersedes: host-specific VPS-readiness packaging assumptions in earlier planning; it does not change ADR-001's full-code, Telegram long-polling, or no-transcript decisions.

## Context

The previous M7 plan described readiness for a specific VPS. The Human has
replaced that target with a Docker-first delivery model: build one application
artifact and promote the same artifact between compatible Docker hosts. The
approved corpus is Confidential, the model service is a separate runtime
dependency, and credentials must remain outside repository and image layers.
The application also needs durable SQLite index and polling state across
container replacement.

## Decision

1. Package the Python 3.12 application, locked runtime dependencies, source,
   and approved 26-document corpus in one OCI image using a multi-stage build.
2. Build the image once for the selected target platform, identify it by
   immutable digest, and run/promote that same artifact on compatible Docker
   hosts. Compose consumes a prebuilt image and does not rebuild it.
3. Treat the image and its build artifacts as Confidential. The corpus is
   included in the image, so image transfer is limited to a Human-approved
   private route. This decision does not authorize registry publication,
   external sharing, or deployment to a named host.
4. Supply environment-specific configuration and secrets at runtime through
   an explicit Compose environment allowlist. Never pass secrets as build
   arguments, copy an `.env` file into the image, or expose resolved
   configuration in logs.
5. Persist the SQLite index and minimal polling/idempotency state in a Docker
   named volume mounted at `/app/.runtime`. Do not store conversation
   transcripts.
6. Run the process as UID/GID `10001`, with a read-only root filesystem,
   dropped Linux capabilities, `no-new-privileges`, bounded temporary storage,
   and no published inbound ports. Telegram long polling remains the inbound
   interaction pattern.
7. Keep the model endpoint external to the image. Configure its URL and model
   identifier for each runtime; the endpoint must be reachable from inside
   the container.
8. Replace the former `M7 — VPS Readiness` milestone with
   `M7 — Docker Packaging & Portable Runtime`. M7 ends with build/runtime
   evidence and an operator handoff, not a release or deployment.

## Consequences

- Updating approved corpus documents requires building a new image and
  rebuilding the active index against the existing runtime volume.
- Replacing a container must retain the named volume; deleting that volume
  intentionally removes the index and technical polling state.
- A compatible Docker host must support the image's target OS and CPU
  architecture. Multi-platform publication is not implied unless a future
  build explicitly creates and verifies a multi-platform manifest.
- A host-local model service must be exposed at an address reachable from the
  container. `host.docker.internal` is the documented default for the local
  operator configuration and may be changed at runtime.
- Docker packaging does not close the known chat-allowlist risk, validate M5
  after the English corpus migration, or replace independent M8 QA/Security.
- Human approval is still required before image distribution, registry use,
  production credentials, a named deployment target, or release.

## Acceptance linkage

Architecture `1.2` adds `AC-037–041` for artifact identity, secret exclusion,
volume persistence, runtime isolation, and approved corpus updates. The
implementation handoff must distinguish static configuration evidence from a
successful image build or runtime observation. Unobserved acceptance remains
`NOT_VERIFIED`.
