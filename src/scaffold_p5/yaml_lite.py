"""Deterministic restricted YAML for P5 schemas. No package-manager pretence."""

from __future__ import annotations

from typing import Any


def dump(data: Any) -> str:
    return _dump(data, 0) + "\n"


def load(text: str) -> Any:
    lines = [ln.rstrip("\n") for ln in text.splitlines() if not _ignore_line(ln)]
    value, next_index = _parse_block(lines, 0, 0)
    if next_index != len(lines):
        leftover = lines[next_index].strip()
        raise ValueError(
            "restricted YAML document has unconsumed content: " + leftover
        )
    return value


def _ignore_line(ln: str) -> bool:
    s = ln.strip()
    return not s or s.startswith("#")


def _dump(data: Any, indent: int) -> str:
    pad = "  " * indent
    if isinstance(data, dict):
        if not data:
            return pad + "{}"
        parts = []
        for key, value in data.items():
            key_s = str(key)
            if isinstance(value, (dict, list)):
                if not value:
                    parts.append(f"{pad}{key_s}: " + ("[]" if isinstance(value, list) else "{}"))
                else:
                    parts.append(f"{pad}{key_s}:")
                    parts.append(_dump(value, indent + 1))
            else:
                parts.append(f"{pad}{key_s}: {_scalar(value)}")
        return "\n".join(parts)
    if isinstance(data, list):
        if not data:
            return pad + "[]"
        parts = []
        for item in data:
            if isinstance(item, (dict, list)):
                inner = _dump(item, indent + 1)
                first, *rest = inner.split("\n")
                parts.append(f"{pad}- {first.lstrip()}")
                parts.extend(rest)
            else:
                parts.append(f"{pad}- {_scalar(item)}")
        return "\n".join(parts)
    return pad + _scalar(data)


def _scalar(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return '"' + _escape_quoted(str(value)) + '"'


def _escape_quoted(text: str) -> str:
    # Encode line breaks so quoted scalars stay on one physical line.
    return (
        text.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
    )


def _unescape_quoted(text: str) -> str:
    # Scan escapes; do not sequential-replace \\ then \n.
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch != "\\" or i + 1 >= n:
            out.append(ch)
            i += 1
            continue
        nxt = text[i + 1]
        if nxt == "n":
            out.append("\n")
        elif nxt == "r":
            out.append("\r")
        elif nxt == '"':
            out.append('"')
        elif nxt == "\\":
            out.append("\\")
        else:
            out.append("\\")
            out.append(nxt)
        i += 2
    return "".join(out)


def _parse_block(lines: list[str], i: int, indent: int) -> tuple[Any, int]:
    if i >= len(lines):
        return {}, i
    raw = lines[i]
    cur = len(raw) - len(raw.lstrip(" "))
    if cur < indent:
        return {}, i
    stripped = raw.strip()
    if stripped == "{}":
        return {}, i + 1
    if stripped == "[]":
        return [], i + 1
    if stripped.startswith("- "):
        return _parse_list(lines, i, cur)
    return _parse_map(lines, i, cur)


def _parse_map(lines: list[str], i: int, indent: int) -> tuple[dict[str, Any], int]:
    out: dict[str, Any] = {}
    while i < len(lines):
        raw = lines[i]
        cur = len(raw) - len(raw.lstrip(" "))
        if cur < indent:
            break
        stripped = raw.strip()
        if stripped.startswith("- "):
            break
        if cur != indent:
            raise ValueError(f"bad indent at: {raw}")
        if ":" not in stripped:
            raise ValueError(f"mapping line is missing a delimiter: {raw}")
        key, _, rest = stripped.partition(":")
        key = key.strip()
        rest = rest.strip()
        if not key:
            raise ValueError(f"empty mapping key at: {raw}")
        i += 1
        if rest in {"", "|"}:
            if i < len(lines):
                nxt = lines[i]
                nindent = len(nxt) - len(nxt.lstrip(" "))
                if nindent > indent:
                    value, i = _parse_block(lines, i, nindent)
                    _assign_key(out, key, value, raw)
                    continue
            _assign_key(out, key, {}, raw)
        else:
            _assign_key(out, key, _parse_scalar(rest), raw)
    return out, i


def _parse_list(lines: list[str], i: int, indent: int) -> tuple[list[Any], int]:
    out: list[Any] = []
    while i < len(lines):
        raw = lines[i]
        cur = len(raw) - len(raw.lstrip(" "))
        if cur < indent:
            break
        stripped = raw.strip()
        if not stripped.startswith("- "):
            if cur == indent:
                raise ValueError(f"unconsumed sibling content after list: {raw}")
            break
        body = stripped[2:]
        i += 1
        if ": " in body or body.endswith(":"):
            key, _, rest = body.partition(":")
            key = key.strip()
            rest = rest.strip()
            if not key:
                raise ValueError(f"empty mapping key at: {raw}")
            item: dict[str, Any] = {}
            _assign_key(item, key, _parse_scalar(rest) if rest else {}, raw)
            if i < len(lines):
                nindent = len(lines[i]) - len(lines[i].lstrip(" "))
                if nindent > indent:
                    extra, i = _parse_map(lines, i, nindent)
                    if rest == "" and extra:
                        item[key] = extra
                    else:
                        for extra_key, extra_value in extra.items():
                            _assign_key(item, extra_key, extra_value, raw)
            out.append(item)
        else:
            out.append(_parse_scalar(body))
    return out, i


def _assign_key(out: dict[str, Any], key: str, value: Any, raw: str) -> None:
    if key in out:
        raise ValueError(f"duplicate mapping key {key!r} at: {raw}")
    out[key] = value


def _parse_scalar(text: str) -> Any:
    if text in {"{}", "[]"}:
        return {} if text == "{}" else []
    if text in {"null", "~"}:
        return None
    if text == "true":
        return True
    if text == "false":
        return False
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        return _unescape_quoted(text[1:-1])
    try:
        if "." in text:
            return float(text)
        return int(text)
    except ValueError:
        return text
