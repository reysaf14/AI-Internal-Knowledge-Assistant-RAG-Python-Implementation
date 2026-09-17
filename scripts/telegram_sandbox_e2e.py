"""Live Telegram sandbox E2E for G3/G4 (AC-006, AC-008, AC-010, AC-027..031).

Closes the *sandbox* half of G3/G4 that the mock/local tests cannot: this drives
the real ``PtbTelegramClient`` boundary and the real ``TelegramPoller`` against
the live Telegram API.

Why the operator must type the questions
----------------------------------------
An earlier revision used a second bot ("Bot B") to send the questions into a
shared group.  That design cannot work, and Telegram documents the reason:

    "Why doesn't my bot see messages from other bots?  Bots talking to each
     other could potentially get stuck in unwelcome loops.  To avoid this, we
     decided that bots will not be able to see messages from other bots
     regardless of mode."
    -- https://core.telegram.org/bots/faq

Measured confirmation before the redesign: Bot B sent a message into the shared
supergroup (``ok=True``, ``message_id=21``) while Bot A's ``getUpdates`` stayed at
zero -- with Bot A already a group member, no webhook set, and privacy mode
disabled.  The message is simply never delivered to the other bot.

The only actor whose messages a bot can observe is a **human**.  So this script
prints the test questions, waits while the operator types them into the group,
and then measures whatever arrives through the real polling path.  A second bot
token is no longer required.

No secret is ever printed: only coarse status, counts, and document filenames
that are already part of the grounded answer contract.
"""
from __future__ import annotations

import argparse
import math
import re
import sys
import time
from pathlib import Path

import httpx

from rag_assistant.answering.service import build_answer_service
from rag_assistant.config import load_config, load_operator_env
from rag_assistant.retrieval.service import Retriever
from rag_assistant.storage.index_store import IndexStore
from rag_assistant.storage.state_store import StateStore
from rag_assistant.telegram.models import IncomingUpdate
from rag_assistant.telegram.poller import TelegramPoller
from rag_assistant.telegram.ptb_client import PtbTelegramClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Two supported questions plus one deliberately out-of-corpus question.  These
# are printed for the operator to type verbatim, so the run is reproducible.
QUESTIONS: tuple[str, ...] = (
    "Jam berapa toko Makmur Jaya tutup?",
    "Berapa hari cuti tahunan karyawan?",
    "Siapa pemenang piala dunia 1998?",
)
EXPECTED_UPDATES = len(QUESTIONS)

POLL_TIMEOUT_SECONDS = 5
DEFAULT_WAIT_SECONDS = 240
DRAIN_POLL_TIMEOUT_SECONDS = 2
DRAIN_IDLE_ROUNDS = 2
HEARTBEAT_SECONDS = 20.0

ABSTENTION_MARKERS = ("tidak menemukan", "tidak tahu", "belum ada informasi")

# The group id is learned from live traffic once, then cached.  Telegram drops
# an update once a higher offset is consumed, so without the cache a second run
# would have to wait for fresh traffic before it could resolve the group again.
CHAT_ID_CACHE = Path(".runtime/sandbox-e2e-chatid.txt")


class TimingBoundary:
    """Wrap the real boundary and record receive->send timing per update."""

    def __init__(self, inner: PtbTelegramClient) -> None:
        self._inner = inner
        self.received: dict[int, float] = {}
        self.sent: dict[int, float] = {}
        self.messages: dict[int, list[str]] = {}

    def get_updates(self, offset: int, timeout_seconds: int):
        updates = self._inner.get_updates(offset, timeout_seconds)
        now = time.perf_counter()
        for update in updates:
            self.received.setdefault(update.update_id, now)
        # Print every arrival the instant it happens, with an explicit flush.
        # Redirected stdout is block-buffered, so without this the only record
        # of an arrival can sit in a buffer that never gets written when the
        # window is cut short -- which makes a delivered question look like a
        # question that never came.
        if updates:
            print(
                "received_ids=" + ",".join(str(u.update_id) for u in updates),
                flush=True,
            )
        return updates

    def send_message(self, chat_id: str, text: str):
        result = self._inner.send_message(chat_id, text)
        now = time.perf_counter()
        # Attach to the newest update that has been received but not yet sent.
        pending = [uid for uid in self.received if uid not in self.sent]
        if pending:
            uid = max(pending)
            self.sent[uid] = now
            self.messages.setdefault(uid, []).append(text)
        return result


def _sanitize(text: str) -> str:
    """Remove any token-shaped or numeric-id-shaped fragment from a line."""
    text = re.sub(r"\b\d{6,12}:[A-Za-z0-9_-]{20,}\b", "[REDACTED]", text)
    return re.sub(r"\bbot\d{6,12}\b", "[REDACTED]", text)


def _print_preconditions() -> None:
    print("PRECONDITIONS_MISSING")
    print("TODO=1. Set TELEGRAM_BOT_TOKEN for the application bot in .env")
    print("TODO=2. Add that bot to one Telegram group")
    print("TODO=3. Disable privacy for it: @BotFather -> /setprivacy -> Disable")
    print("     (privacy mode ON hides plain group messages from the bot)")
    print("TODO=4. Send any message in that group, then re-run this script")
    print(
        "NOTE=A second bot cannot be the sender: Telegram never delivers messages "
        "from one bot to another, regardless of privacy mode."
    )


def _print_group_discovery_help() -> None:
    print("BLOCKED=no_group_traffic")
    print(
        "WHY=the queue is empty, so the shared group id cannot be learned. "
        "Telegram discards an update once a higher offset is consumed, which is "
        "why re-running alone does not help."
    )
    print("ACTION=send any message in the group, then re-run")
    print("ALT=pass the group id directly: --chat-id -100xxxxxxxxxx")
    print(
        "NOTE=if your own message never reaches the bot, privacy mode is still "
        "enabled for it (@BotFather -> /setprivacy -> Disable)."
    )


def _prewarm_model(cfg) -> bool:
    """Load the model before the clock starts, and say so in the output.

    A cold local model needs ~25-30 s for its first answer, which can never fit
    the locked <5 s budget.  A continuously running bot keeps its model
    resident, so the sandbox measures the latency that actually matters by
    paying the load cost once, up front -- and prints a flag so the evidence is
    unambiguous about which condition was measured.
    """
    base = cfg.llm_base_url.rstrip("/").removesuffix("/v1")
    payload = {
        "model": cfg.llm_model,
        "messages": [{"role": "user", "content": "ping"}],
        "stream": False,
        "think": False,
        "options": {"num_predict": 1},
    }
    started = time.perf_counter()
    try:
        response = httpx.post(f"{base}/api/chat", json=payload, timeout=180.0)
    except httpx.HTTPError:
        print("model_prewarmed=False category=MODEL_UNREACHABLE")
        return False
    elapsed = (time.perf_counter() - started) * 1000
    ok = response.status_code < 400
    print(f"model_prewarmed={ok} prewarm_ms={elapsed:.0f}")
    return ok


def _pending_count(token: str) -> int | None:
    """How many updates Telegram is holding for this bot, or ``None``.

    This is the measurement that separates the two remaining causes when the
    poller reports fewer updates than the operator sent.  ``getWebhookInfo`` is
    a plain read: unlike ``getUpdates`` it consumes nothing, so it is safe to
    call mid-run.

    * pending > our received count -> the updates *are* queued but are not
      reaching this consumer, which points at the offset or a competing reader.
    * pending == our received count (typically 0) -> Telegram never queued
      them, so the loss happened before delivery and nothing in this process
      can explain it.
    """
    base = f"https://api.telegram.org/bot{token}/getWebhookInfo"
    try:
        response = httpx.get(base, timeout=15.0)
        payload = response.json()
    except (httpx.HTTPError, ValueError):
        return None
    result = payload.get("result") or {}
    value = result.get("pending_update_count")
    return value if isinstance(value, int) else None


def _probe_updates(probe: PtbTelegramClient) -> tuple[IncomingUpdate, ...]:
    """Read another bot's pending updates without consuming them.

    Used only for diagnosis.  The offset stays at ``0`` on purpose: this is a
    read-only look, and advancing it would silently drop traffic.  An error
    means "could not tell", returned as empty so a transient failure never
    masquerades as a confirmed cause.
    """
    try:
        return probe.get_updates(0, DRAIN_POLL_TIMEOUT_SECONDS)
    except Exception:  # noqa: BLE001 - diagnosis must never break the run
        return ()


def _drain_backlog(
    client: PtbTelegramClient,
    offset: int,
    max_wait_seconds: int,
    require_group: bool = False,
) -> tuple[int, int]:
    """Consume pending updates; return ``(group_chat_id, next_offset)``.

    Draining to empty is what makes the measured run trustworthy: the returned
    offset seeds the poller, so its counters describe the test questions and
    nothing else.  Stopping at the first group message leaves the earlier
    traffic in the queue for the poller to re-read.

    ``require_group`` distinguishes the two jobs this function does:

    * **Draining** (group id already known): an empty queue means the job is
      done, so two short empty polls end it.
    * **Discovery** (group id still unknown): an empty queue is transient -- the
      operator simply has not typed yet.  Breaking on the idle round would
      cancel the wait window after ~4 s, so keep polling until the deadline.
    """
    deadline = time.perf_counter() + max_wait_seconds
    next_beat = time.perf_counter() + HEARTBEAT_SECONDS
    chat_id = 0
    idle = 0
    while time.perf_counter() < deadline:
        try:
            raw = client.get_updates(offset, DRAIN_POLL_TIMEOUT_SECONDS)
        except Exception as exc:  # noqa: BLE001 - surface category only
            print(f"group_lookup_error={type(exc).__name__}")
            return 0, offset
        if not raw:
            idle += 1
            if time.perf_counter() >= next_beat:
                remaining = max(0, int(deadline - time.perf_counter()))
                print(f"waiting_for_group_message remaining_s={remaining}")
                next_beat = time.perf_counter() + HEARTBEAT_SECONDS
            if idle >= DRAIN_IDLE_ROUNDS and (chat_id or not require_group):
                break
            continue
        idle = 0
        for update in raw:
            offset = max(offset, update.update_id + 1)
            if not chat_id and update.chat_id and update.chat_id.startswith("-"):
                chat_id = int(update.chat_id)
    return chat_id, offset


def _read_cached_chat_id(root: Path) -> int:
    """Return the previously discovered group id, or 0 when unknown."""
    path = root / CHAT_ID_CACHE
    if not path.is_file():
        return 0
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except ValueError:
        return 0


def _write_cached_chat_id(root: Path, chat_id: int) -> None:
    path = root / CHAT_ID_CACHE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{chat_id}\n", encoding="utf-8")


def _collect(
    build_poller,
    boundary: TimingBoundary,
    expected: int,
    wait_seconds: int,
    pending_probe=None,
):
    """Poll one iteration at a time until ``expected`` updates arrive.

    ``TelegramPoller.run`` honours ``max_iterations`` as a hard *attempt* cap, so
    a single call would either stop before the operator has finished typing or
    keep going after every question is answered.  A fresh poller is therefore
    built per iteration, sharing one ``StateStore`` -- the offset and the
    processed-update ledger live in that store, so each short-lived poller
    resumes exactly where the previous one stopped.  This drives the loop
    through its public surface only and leaves the approved M4 code untouched.

    Returned counters are summed across iterations, and ``updates`` is reported
    exactly once per update because deduplication is keyed on the shared store.
    """
    totals = {
        "attempts": 0,
        "polls": 0,
        "updates": 0,
        "answers_delivered": 0,
        "duplicates": 0,
        "rejected": 0,
        "sends_failed": 0,
        "sends_unknown": 0,
        "poll_failures": 0,
        "pruned": 0,
    }
    per_iteration = max(POLL_TIMEOUT_SECONDS, 1)
    max_iterations = max(1, math.ceil(wait_seconds / per_iteration))
    deadline = time.perf_counter() + wait_seconds
    next_beat = time.perf_counter() + HEARTBEAT_SECONDS

    for _ in range(max_iterations):
        # ``run()`` absorbs ``TelegramError`` from its polling path, but anything
        # outside that contract (an adapter-level ``RuntimeError``, a closed
        # event loop from the async boundary, a state-store fault) would
        # propagate and end the whole wait window on the first hiccup -- which is
        # how an earlier run died at 152 s of a 420 s window with the operator's
        # questions still in flight.  A transient fault must cost one iteration,
        # not the run, so it is counted and reported instead.
        try:
            counters = build_poller().run()
        except Exception as exc:  # noqa: BLE001 - a poll fault must not end the window
            totals["poll_failures"] += 1
            print(
                f"iteration_error={type(exc).__name__}"
                f" at_received={totals['updates']}/{expected}",
                flush=True,
            )
            if time.perf_counter() >= deadline:
                return totals
            continue
        for field in totals:
            totals[field] += getattr(counters, field)
        if totals["updates"] >= expected:
            return totals
        if time.perf_counter() >= deadline:
            return totals
        if time.perf_counter() >= next_beat:
            remaining = max(0, int(deadline - time.perf_counter()))
            # ``polls`` and ``poll_failures`` are part of the heartbeat, not just
            # the final summary: when a window is cut short the summary never
            # prints, and an undetectable poll failure then looks exactly like a
            # queue that never delivered anything.
            print(
                f"waiting_for_questions received={totals['updates']}"
                f"/{expected} polls={totals['polls']}"
                f" poll_failures={totals['poll_failures']}"
                f" pending_at_telegram={pending_probe() if pending_probe else 'n/a'}"
                f" remaining_s={remaining}"
            )
            next_beat = time.perf_counter() + HEARTBEAT_SECONDS

    print(f"timeout_after_s={wait_seconds} received={totals['updates']}/{expected}")
    return totals


def _stamp() -> str:
    """Local wall-clock with seconds.

    Every line of a live run needs an absolute time, not just an elapsed counter:
    the operator reports when they sent each message in wall-clock terms, and a
    log that only counts down cannot be lined up against that.  Without it a
    "the poller missed my question" report is untestable after the fact.
    """
    return time.strftime("%H:%M:%S")


def _say(message: str) -> None:
    """Print one trace line, timestamped and flushed immediately.

    Flushing matters more than it looks: when a window is killed from outside,
    anything still sitting in the stdout buffer is lost, and the log then ends
    mid-run with no explanation -- which reads exactly like a hung process
    rather than a killed one.
    """
    print(f"[{_stamp()}] {message}", flush=True)


def _main() -> int:
    # Line-buffered so a window killed from outside still leaves every trace line
    # that was printed before the kill.  Without this the log truncates wherever
    # the block buffer happened to fill, and a killed run is indistinguishable
    # from a hung one.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument(
        "--chat-id",
        type=int,
        default=0,
        help="Target group id; skips live discovery when supplied",
    )
    parser.add_argument(
        "--wait-seconds",
        type=int,
        default=DEFAULT_WAIT_SECONDS,
        help="How long to wait for the operator's questions (default: %(default)s)",
    )
    args = parser.parse_args()

    root = args.project_root.resolve()
    load_operator_env(root)
    cfg = load_config(root)

    if not cfg.telegram_bot_token:
        _say("bot_a_token_present=False")
        _print_preconditions()
        return 4

    bot_a = PtbTelegramClient(
        token=cfg.telegram_bot_token,
        poll_timeout_seconds=cfg.telegram_poll_timeout,
        request_timeout_seconds=cfg.telegram_request_timeout,
    )

    # Phase 1: live authentication for the application bot (G4 auth path).
    _say("== phase1 getMe ==")
    try:
        bot_a.get_updates(offset=0, timeout_seconds=1)
        _say("bot_a_reachable=True")
    except Exception as exc:  # noqa: BLE001
        _say(f"bot_a_reachable=False category={_sanitize(type(exc).__name__)}")
        return 1

    # Phase 2: resolve the target chat.  The state store is opened first: an
    # explicit chat id needs its stored offset, and discovery must write the
    # resulting seed back into the same store either way.
    state_dir = root / ".runtime"
    state_dir.mkdir(exist_ok=True)
    state_store = StateStore(state_dir / "sandbox-e2e-state.sqlite3")
    _say("== phase2 target chat ==")
    chat_id = args.chat_id or _read_cached_chat_id(root)
    if chat_id:
        # An explicit chat id means there is nothing to discover -- and nothing
        # safe to drain.  Draining seeds the poller at a high offset, and a
        # confirmed offset makes Telegram discard every update below it, so a
        # sweep that happens to run while the operator is typing would silently
        # swallow exactly the questions this run exists to measure.  The
        # pass-through poller below already skips anything older than the seed,
        # so the truthful seed is the stored offset, not a fresh sweep.
        offset_after_drain = state_store.get_polling_offset()
        _say("drain=skipped (explicit chat id; operator traffic must survive)")
    else:
        # Discovery still needs the queue: the group id can only be learned from
        # inbound traffic, and that traffic must not be consumed before the
        # measured run or the run has nothing left to answer.
        discovered, offset_after_drain = _drain_backlog(
            bot_a,
            offset=0,
            max_wait_seconds=min(args.wait_seconds, 120),
            require_group=True,
        )
        chat_id = discovered
    source = "cli" if args.chat_id else "cache" if chat_id else "inbound"
    _say(f"chat_source={source}")
    if chat_id:
        _write_cached_chat_id(root, chat_id)
    if not chat_id:
        _say("chat_found=False")
        _print_group_discovery_help()
        return 4
    _say(f"chat_found=True kind={'group' if chat_id < 0 else 'private'}")

    # Phase 2.5: pay the model load cost before any latency is measured.
    _say("== phase2b model warmup ==")
    _prewarm_model(cfg)

    # Never rewind: Telegram only drops the backlog once a *higher* offset is
    # used, so seeding below the stored value would re-read confirmed traffic.
    seed = max(offset_after_drain, state_store.get_polling_offset())
    state_store.set_polling_offset(seed)
    _say(f"offset_seeded={seed}")

    # Phase 3: the operator types the questions; the real poller answers them.
    _say("== phase3 live e2e ==")
    _say(f"expected_updates={EXPECTED_UPDATES}")
    for index, question in enumerate(QUESTIONS, start=1):
        _say(f"ask_{index}={question}")
    _say(f"ACTION=send those {EXPECTED_UPDATES} messages into the chat now")

    boundary = TimingBoundary(bot_a)

    def build_poller() -> TelegramPoller:
        """One short-lived poller sharing the persistent state store."""
        return TelegramPoller(
            boundary=boundary,
            state_store=state_store,
            retriever=Retriever(IndexStore(cfg.resolve_index_path())),
            answer_service=build_answer_service(cfg),
            poll_timeout_seconds=POLL_TIMEOUT_SECONDS,
            max_question_chars=cfg.max_question_chars,
            max_iterations=1,
        )

    counters = _collect(
        build_poller,
        boundary,
        EXPECTED_UPDATES,
        args.wait_seconds,
        pending_probe=lambda: _pending_count(cfg.telegram_bot_token),
    )

    # Captured the moment the window ends, before anything else can touch the
    # queue: "how many were still queued" is the one number that tells the two
    # remaining causes apart after the fact.
    _say(
        f"end_of_run pending_at_telegram={_pending_count(cfg.telegram_bot_token)}"
    )

    _say(f"updates={counters['updates']} delivered={counters['answers_delivered']}")
    _say(f"duplicates={counters['duplicates']} rejected={counters['rejected']}")
    _say(
        f"sends_failed={counters['sends_failed']}"
        f" sends_unknown={counters['sends_unknown']}"
    )
    _say(f"poll_failures={counters['poll_failures']}")
    if counters["updates"] != EXPECTED_UPDATES:
        _say(
            f"WARN=updates({counters['updates']}) != expected({EXPECTED_UPDATES}); "
            "the operator sent a different number of messages, or other chat "
            "traffic was in flight during the run"
        )

    statuses = []
    for uid in sorted(boundary.received):
        bodies = boundary.messages.get(uid, [])
        body = bodies[0] if bodies else ""
        latency_ms = None
        if uid in boundary.sent:
            latency_ms = (boundary.sent[uid] - boundary.received[uid]) * 1000
        sourced = "sumber" in body.casefold()
        abstained = any(m in body.casefold() for m in ABSTENTION_MARKERS)
        statuses.append((len(bodies), sourced, abstained, latency_ms))
        lat = f"{latency_ms:.0f}ms" if latency_ms is not None else "none"
        _say(
            f"update={uid}|responses={len(bodies)}|sourced={sourced}|"
            f"abstained={abstained}|latency={lat}"
        )

    answered = [s for s in statuses if s[0] == 1]
    sourced_count = sum(1 for s in answered if s[1])
    abstained_count = sum(1 for s in answered if s[2])
    dup = sum(max(c - 1, 0) for c, _s, _a, _l in statuses)
    latencies = [s[3] for s in answered if s[3] is not None]
    within = sum(1 for v in latencies if v < 5000)
    _say(f"answered_updates={len(answered)}")
    _say(f"sourced={sourced_count} abstained={abstained_count} duplicates={dup}")
    _say(f"latency_within_5s={within}/{len(latencies)}")
    _say("verification_level=telegram-sandbox")
    return 0


if __name__ == "__main__":
    sys.exit(_main())
