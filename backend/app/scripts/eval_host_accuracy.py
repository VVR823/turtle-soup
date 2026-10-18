"""Compatibility entry only; old reports/data remain untouched.

Use explicit eval.run_cli run/compare arguments. No default dataset, old filters,
display-text guessing, environment mutation or real-provider initialization.
"""


def main(argv=None):
    # Support both -m and this fixed local script path, without import-time work.
    import sys
    from pathlib import Path
    backend = str(Path(__file__).resolve().parents[2])
    if backend not in sys.path:
        sys.path.insert(0, backend)
    from eval.run_cli import main as run_main
    return run_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
