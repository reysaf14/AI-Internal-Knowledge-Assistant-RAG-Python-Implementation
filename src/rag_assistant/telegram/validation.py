"""Update validation for the Telegram boundary.

Validation runs *before* retrieval and before any model call, so an invalid
update can never trigger a corpus read or a generation. Each rejection reason
maps to exactly one short, policy-free Indonesian reply (AC-007: "maksimal satu
pesan penjelasan yang aman").

The decision object excludes the question text from ``repr`` so a logged
decision cannot leak the user's message.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from rag_assistant.telegram.models import IncomingUpdate
from rag_assistant.telegram.policy import MAX_SAFE_REPLY_CHARS

HELP_COMMANDS = frozenset({"/start", "/help"})

HELP_TEXT = (
    "Kirim pertanyaan teks tentang kebijakan, SOP, atau informasi resmi toko. "
    "Saya menjawab hanya dari dokumen resmi dan menyertakan sumbernya. "
    "Jika dokumen tidak mendukung jawabannya, saya akan bilang tidak tahu."
)
REPLY_EMPTY = "Pesan kosong. Silakan kirim pertanyaan teks tentang kebijakan atau SOP resmi."
REPLY_NON_TEXT = "Saya hanya memproses pertanyaan teks. Kirim pertanyaan sebagai teks."
REPLY_UNKNOWN_COMMAND = "Perintah tidak dikenal. Kirim pertanyaan teks, atau gunakan /help."
REPLY_TOO_LONG = "Pertanyaan terlalu panjang. Mohon kirim pertanyaan yang lebih singkat."


class UpdateKind(Enum):
    """What the boundary decided to do with an update."""

    QUESTION = "question"
    HELP = "help"
    REJECTED = "rejected"


class RejectionReason(Enum):
    """Why an update was refused without touching the corpus or a model."""

    NO_CHAT = "no_chat"
    NON_TEXT = "non_text"
    EMPTY = "empty"
    UNKNOWN_COMMAND = "unknown_command"
    TOO_LONG = "too_long"


@dataclass(frozen=True)
class ValidationDecision:
    """Outcome of validating one update."""

    kind: UpdateKind
    question: str = field(default="", repr=False)
    reason: RejectionReason | None = None
    safe_reply: str = ""

    @property
    def needs_retrieval(self) -> bool:
        """True only when the corpus may be read for this update."""
        return self.kind is UpdateKind.QUESTION


def _command_of(text: str) -> str | None:
    """Return the lowercased command token, stripping a ``@botname`` suffix."""
    stripped = text.strip()
    if not stripped.startswith("/"):
        return None
    token = stripped.split(maxsplit=1)[0]
    return token.split("@", maxsplit=1)[0].casefold()


def validate_update(
    update: IncomingUpdate, max_question_chars: int
) -> ValidationDecision:
    """Classify an update as a question, a help command, or a rejection."""
    if not update.chat_id or not update.chat_id.strip():
        return ValidationDecision(UpdateKind.REJECTED, reason=RejectionReason.NO_CHAT)

    if update.text is None:
        return ValidationDecision(
            UpdateKind.REJECTED,
            reason=RejectionReason.NON_TEXT,
            safe_reply=REPLY_NON_TEXT,
        )

    text = update.text.strip()
    if not text:
        return ValidationDecision(
            UpdateKind.REJECTED,
            reason=RejectionReason.EMPTY,
            safe_reply=REPLY_EMPTY,
        )

    command = _command_of(text)
    if command is not None:
        if command in HELP_COMMANDS:
            return ValidationDecision(UpdateKind.HELP, safe_reply=HELP_TEXT)
        return ValidationDecision(
            UpdateKind.REJECTED,
            reason=RejectionReason.UNKNOWN_COMMAND,
            safe_reply=REPLY_UNKNOWN_COMMAND,
        )

    if max_question_chars <= 0 or len(text) > max_question_chars:
        return ValidationDecision(
            UpdateKind.REJECTED,
            reason=RejectionReason.TOO_LONG,
            safe_reply=REPLY_TOO_LONG,
        )

    return ValidationDecision(UpdateKind.QUESTION, question=text)


def safe_reply_within_budget(text: str) -> bool:
    """True when a canned reply respects the locked reply budget."""
    return 0 < len(text) <= MAX_SAFE_REPLY_CHARS
