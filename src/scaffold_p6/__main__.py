from __future__ import annotations

import argparse
import json
from pathlib import Path

from scaffold_p5.result import result_dict
from scaffold_p6.engine import TestEngine


def main() -> int:
    parser = argparse.ArgumentParser(description="P6 Test candidate runner")
    parser.add_argument("mode", nargs="?", default="scoped_verification")
    parser.add_argument("--host", required=True)
    parser.add_argument("--package", default=None)
    args = parser.parse_args()
    result = TestEngine(args.host, args.package).run(args.mode)
    print(json.dumps(result_dict(result), indent=2))
    return 0 if result.outcome in {"COMPLETED", "BLOCKED", "NEEDS_HUMAN"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
