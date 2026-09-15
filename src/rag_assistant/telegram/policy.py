"""Locked M4 runtime policy.

These bounds are module-level constants with rationale rather than magic numbers
buried in the loop, because architecture.md requires the retention window and
retry/backoff bounds to be locked and recorded *before* implementation:

- ``architecture.md``: "Retensi state teknis dibatasi pada kebutuhan
  deduplication/recovery ... durasi retention yang spesifik harus dikunci
  Engineer sebelum implementasi."
- ``architecture.md``: polling performs "reconnect/backoff terbatas"; send has a
  timeout and reports ``UNKNOWN`` for an undecidable result.

Each value is restated with its justification in the M4 report §2.
"""
from __future__ import annotations

# Deduplication retention. Telegram redelivers unconfirmed updates within about
# a day; a week keeps a generous margin while the table stays tiny (one row per
# handled update, technical identifiers only).
PROCESSED_UPDATE_RETENTION_DAYS = 7

# Pruning runs on startup and then every N successful polls, so the loop never
# pays the DELETE cost on the hot path.
PRUNE_EVERY_N_POLLS = 100

# Bounded reconnect/backoff for the polling request. Capped so the bot keeps
# trying forever without hammering Telegram, and so a long outage never turns
# into a burst of queued answers.
BACKOFF_INITIAL_SECONDS = 1.0
BACKOFF_MULTIPLIER = 2.0
BACKOFF_MAX_SECONDS = 30.0
BACKOFF_MAX_SHIFT = 6

# Outbound send bounds. Escalating attempts apply only to a *retryable*
# condition (rate limit). A timeout/disconnect is recorded as UNKNOWN and is
# never retried, because a second send could duplicate a message that already
# left the machine.
MAX_SEND_ATTEMPTS = 2
MAX_SAFE_REPLY_CHARS = 300

# Single-instance guard file name, created next to the runtime state.
LOCK_FILE_NAME = "bot.lock"

# Long-poll read timeout must leave room for the poll timeout itself.
POLL_READ_TIMEOUT_GRACE_SECONDS = 5
