"""Retired legacy writer. Fail-closed shim for old cron/manual imports.

The old job rewrote JSONL, changed rules without version publication, deleted
historical games, and restarted the server. None is permitted after TS-02.
Versioned human-reviewed publication is delivered separately in TS-10/15.
Actual server cron/timer inventory is still a deployment prerequisite.
"""


class LegacyWriterDisabled(RuntimeError):
    pass


def run_merge(feedback_path: str, verified_qa_path: str, *, restart_backend: bool = True) -> int:
    raise LegacyWriterDisabled("Legacy direct rule merge is disabled; use versioned publication")


def cleanup_old_sessions(days_ended: int = 7, days_stale_playing: int = 30) -> int:
    raise LegacyWriterDisabled("Automatic history deletion is disabled")


def main() -> int:
    print("Legacy merge/cleanup disabled. No data written, deleted, or service restarted.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
