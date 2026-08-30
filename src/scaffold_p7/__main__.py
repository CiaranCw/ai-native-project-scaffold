from __future__ import annotations

import argparse
import json
from pathlib import Path

from scaffold_p5.result import result_dict
from scaffold_p7.engine import DevelopEngine


def main() -> int:
    parser = argparse.ArgumentParser(description="P7 Develop candidate runner")
    parser.add_argument("mode", nargs="?", default="normal_task")
    parser.add_argument("--host", required=True)
    parser.add_argument("--package", default=None)
    parser.add_argument("--task-id", default=None)
    args = parser.parse_args()
    result = DevelopEngine(args.host, args.package).run(
        args.mode,
        task_id=args.task_id,
    )
    print(json.dumps(result_dict(result), indent=2))
    return 0 if result.outcome in {"COMPLETED", "BLOCKED", "NEEDS_HUMAN"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
