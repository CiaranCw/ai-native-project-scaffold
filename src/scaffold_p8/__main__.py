from __future__ import annotations

import argparse
import json
from pathlib import Path

from scaffold_p5.result import result_dict
from scaffold_p8.engine import SubmitEngine


def main() -> int:
    parser = argparse.ArgumentParser(description="P8 Submit Skill")
    parser.add_argument("host", type=Path)
    parser.add_argument("--task-id", dest="task_id")
    args = parser.parse_args()
    result = SubmitEngine(args.host).run(task_id=args.task_id)
    print(json.dumps(result_dict(result), indent=2))
    return 0 if result.outcome == "COMPLETED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
