"""Distribution-side CLI for project-local consumer installation."""

from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from scaffold_p5.consumer_install import distribution_cli


def main() -> int:
    return distribution_cli()


if __name__ == "__main__":
    raise SystemExit(main())
