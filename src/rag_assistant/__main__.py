"""Entry point dispatch: ingest (rebuild corpus) atau bot (Telegram polling).

Usage:
    python -m rag_assistant ingest   -- rebuild knowledge base index
    python -m rag_assistant bot      -- start Telegram polling bot
    python -m rag_assistant validate ingest -- validate local ingest readiness
    python -m rag_assistant validate bot    -- validate bot readiness without network
"""
from __future__ import annotations

import argparse
import sys


def _run_ingest() -> None:
    from rag_assistant.config import load_config, validate_runtime_config
    from rag_assistant.ingestion.builder import rebuild_corpus

    cfg = load_config()
    validate_runtime_config(cfg, "ingest")
    result = rebuild_corpus(cfg)
    print(
        f"Corpus rebuilt: version={result.corpus_version} "
        f"files={result.file_count} chunks={result.chunk_count}"
    )
    if not result.success:
        print(f"ERROR: {result.error_message}", file=sys.stderr)
        raise SystemExit(1)


def _run_bot() -> None:
    from rag_assistant.answering.service import build_answer_service
    from rag_assistant.config import load_config, validate_runtime_config
    from rag_assistant.retrieval.service import (
        Retriever,
        build_retrieval_policy,
    )
    from rag_assistant.storage.index_store import IndexStore
    from rag_assistant.storage.state_store import StateStore
    from rag_assistant.telegram.lock import InstanceLockError, SingleInstanceLock
    from rag_assistant.telegram.policy import LOCK_FILE_NAME
    from rag_assistant.telegram.poller import TelegramPoller
    from rag_assistant.telegram.ptb_client import PtbTelegramClient

    cfg = load_config()
    validate_runtime_config(cfg, "bot")

    runtime_dir = cfg.resolve_index_path().parent
    poller = TelegramPoller(
        boundary=PtbTelegramClient(
            token=cfg.telegram_bot_token,
            poll_timeout_seconds=cfg.telegram_poll_timeout,
            request_timeout_seconds=cfg.telegram_request_timeout,
        ),
        state_store=StateStore(runtime_dir / "bot_state.sqlite3"),
        retriever=Retriever(
            IndexStore(cfg.resolve_index_path()),
            policy=build_retrieval_policy(cfg.rag_context_limit),
        ),
        answer_service=build_answer_service(cfg),
        poll_timeout_seconds=cfg.telegram_poll_timeout,
        max_question_chars=cfg.max_question_chars,
    )

    try:
        with SingleInstanceLock(runtime_dir / LOCK_FILE_NAME):
            poller.run()
    except InstanceLockError:
        print(
            '{"status":"error","category":"ALREADY_RUNNING",'
            '"message":"another bot instance is already running"}',
            file=sys.stderr,
        )
        raise SystemExit(4) from None


def _run_validate(target: str) -> None:
    from rag_assistant.config import load_config, validate_runtime_config

    cfg = load_config()
    validate_runtime_config(cfg, target)
    print(f"Configuration valid for {target}")


def main() -> None:
    from pathlib import Path

    from rag_assistant.config import load_operator_env

    load_operator_env(Path.cwd())
    parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    parser.add_argument(
        "command", choices=["ingest", "bot", "validate"], help="Operational command"
    )
    parser.add_argument("target", nargs="?", choices=["ingest", "bot"])
    args = parser.parse_args()

    if args.command == "ingest":
        _run_ingest()
    elif args.command == "bot":
        _run_bot()
    elif args.command == "validate":
        if not args.target:
            parser.error("validate requires a target: ingest or bot")
        _run_validate(args.target)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001 - top-level guard maps any unexpected error to exit 1
        sys.exit(1)
