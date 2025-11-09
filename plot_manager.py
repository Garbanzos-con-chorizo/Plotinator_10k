from __future__ import annotations

import sys

from engine.runner import run_batch


def main(argv: list[str] | None = None) -> int:
    args = sys.argv if argv is None else argv
    config_path = args[1] if len(args) > 1 else "config.json"

    try:
        run_batch(config_path)
    except Exception as exc:  # noqa: BLE001 - convert to CLI status code
        print(f"[X] {exc}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
