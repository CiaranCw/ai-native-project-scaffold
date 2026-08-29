from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

from scaffold_p5 import yaml_lite


def read_text(path: str | Path) -> str:
    return Path(path).read_text(encoding="utf-8")


def write_text_atomic(path: str | Path, text: str) -> None:
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, dest)


def read_yaml(path: str | Path) -> Any:
    return yaml_lite.load(read_text(path))


def write_yaml_atomic(path: str | Path, data: Any) -> None:
    write_text_atomic(path, yaml_lite.dump(data))


def sha256_bytes(*parts: bytes) -> str:
    h = hashlib.sha256()
    for part in parts:
        h.update(part)
    return h.hexdigest()


def sha256_text(*parts: str) -> str:
    return sha256_bytes(*(p.encode("utf-8") for p in parts))


def list_files(root: str | Path) -> list[str]:
    base = Path(root)
    out: list[str] = []
    if not base.exists():
        return out
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        for name in filenames:
            full = Path(dirpath) / name
            out.append(str(full.relative_to(base)).replace("\\", "/"))
    return sorted(out)


def file_digest(path: str | Path) -> str:
    return sha256_bytes(Path(path).read_bytes())
