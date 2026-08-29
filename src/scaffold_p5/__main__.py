from __future__ import annotations

import argparse
import json
from pathlib import Path

from scaffold_p5.engine import UnderstandEngine
from scaffold_p5.result import result_dict


def main() -> int:
    parser = argparse.ArgumentParser(description="P5 Understand candidate runner")
    parser.add_argument("mode", choices=["bootstrap", "full", "refresh", "compatibility"])
    parser.add_argument("--host", required=True)
    parser.add_argument("--distribution", required=True, help="Fixture or Distribution root with releases/ and packages/")
    parser.add_argument("--release", default="rel-r1")
    parser.add_argument("--understand", default=None)
    args = parser.parse_args()
    from scaffold_p5.distribution import load_fixture_distribution

    dist = load_fixture_distribution(
        Path(args.distribution),
        selected_release_id=args.release,
        actual_understand_version=args.understand,
    )
    result = UnderstandEngine(args.host, dist).run(args.mode)
    print(json.dumps(result_dict(result), indent=2))
    return 0 if result.outcome == "COMPLETED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
