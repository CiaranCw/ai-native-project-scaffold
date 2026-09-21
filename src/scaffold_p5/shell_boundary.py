"""Hard-boundary classification for ordinary project shell commands.

Not a Skill and not a command allowlist. Official Scaffold launcher
invocations are classified before this module is consulted. Remaining
commands are autonomous unless they cross a narrow safety/governance
boundary.
"""

from __future__ import annotations

from pathlib import Path

from scaffold_p5.client_support import (
    normalize_path_operand,
    path_operand_has_glob,
    path_operand_selects_protected_authority,
)


GIT_NAMES = frozenset({"git"})
PYTHON_NAMES = frozenset({"python", "python3"})
NODE_NAMES = frozenset({"node", "nodejs"})
RUBY_NAMES = frozenset({"ruby"})
PERL_NAMES = frozenset({"perl"})
POWERSHELL_NAMES = frozenset({"powershell", "pwsh"})
DELETE_NAMES = frozenset(
    {"rm", "rmdir", "rd", "del", "erase", "remove-item", "rmuser"}
)
DIRECTORY_RELOCATION_NAMES = frozenset(
    {"mv", "move", "rename", "ren", "move-item", "rename-item"}
)
DIRECTORY_REMOVE_NAMES = frozenset({"rmdir", "rd"})
FS_MUTATION_NAMES = frozenset(
    {
        "mv",
        "move",
        "cp",
        "copy",
        "xcopy",
        "robocopy",
        "rename",
        "ren",
        "rsync",
        "ln",
        "link",
        "mklink",
        "copy-item",
        "move-item",
        "rename-item",
        "new-item",
    }
)
ATTACK_TOOLS = frozenset(
    {
        "nmap",
        "ncat",
        "sqlmap",
        "hydra",
        "john",
        "hashcat",
        "msfconsole",
        "msfvenom",
        "aircrack-ng",
        "aircrack",
        "nikto",
        "burpsuite",
        "zap-cli",
        "gobuster",
        "ffuf",
        "wpscan",
        "ettercap",
        "responder",
        "mimikatz",
        "crackmapexec",
        "netexec",
        "metasploit",
    }
)
GIT_PUBLICATION = frozenset({"commit", "push"})
GIT_DESTRUCTIVE = frozenset(
    {
        "rebase",
        "reset",
        "clean",
        "filter-branch",
        "filter-repo",
        "am",
    }
)
# Path-mutating Git verbs that can relocate, remove, overwrite, or restore
# working-tree files. Inspection verbs stay outside this set so git status /
# log / diff / show remain autonomous even when they mention protected paths.
GIT_PATH_MUTATION = frozenset({"mv", "rm", "checkout", "restore"})
GIT_GLOBAL_VALUE_FLAGS = frozenset(
    {
        "-C",
        "-c",
        "--git-dir",
        "--work-tree",
        "--namespace",
        "--config-env",
        "--super-prefix",
        "--list-cmds",
    }
)
INLINE_EVAL_REASON = (
    "inline interpreter evaluation is a hard mutation/eval boundary"
)
EXECUTABLE_SUFFIXES = (".exe", ".cmd", ".bat", ".ps1", ".com")


def ordinary_shell_hard_boundary(
    argv: list[str],
    host: str | Path,
) -> str | None:
    """Return a deny reason if ``argv`` crosses a hard boundary, else None."""
    if not argv:
        return "empty shell command is not an ordinary project command"
    host_root = Path(host).resolve()
    name = command_basename(argv[0])
    if name in ATTACK_TOOLS:
        return (
            "prohibited security/attack-oriented operation is a hard boundary"
        )
    if _relative_executable_escape(argv[0], host_root):
        return f"{argv[0]} is outside the project/workspace authority boundary"
    outside = _outside_workspace_argument(argv, host_root)
    if outside:
        return outside
    if name in GIT_NAMES:
        return _git_hard_boundary(argv, host_root)
    if name in PYTHON_NAMES and _has_flag(argv, {"-c"}):
        return INLINE_EVAL_REASON
    if name in NODE_NAMES and _has_flag(argv, {"-e", "--eval"}):
        return INLINE_EVAL_REASON
    if name in RUBY_NAMES and _has_flag(argv, {"-e"}):
        return INLINE_EVAL_REASON
    if name in PERL_NAMES and _has_flag(argv, {"-e", "-E"}):
        return INLINE_EVAL_REASON
    if name in POWERSHELL_NAMES and _has_flag(
        argv, {"-command", "-c", "-encodedcommand", "-enc"}
    ):
        return INLINE_EVAL_REASON
    if name in FS_MUTATION_NAMES or name in DELETE_NAMES:
        consume = _operation_consumes_descendants(name, argv)
        governance = _governance_mutation_boundary(
            argv, host_root, consume_descendants=consume
        )
        if governance:
            return governance
    if name in DELETE_NAMES:
        return _deletion_hard_boundary(argv, host_root)
    return None


def command_basename(token: str) -> str:
    raw = str(token or "").replace("\\", "/").strip()
    name = Path(raw).name.lower()
    for suffix in EXECUTABLE_SUFFIXES:
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def _git_hard_boundary(argv: list[str], host_root: Path) -> str | None:
    outside = _git_dir_outside_workspace(argv, host_root)
    if outside:
        return outside
    subcommand, rest = _git_subcommand(argv)
    if not subcommand:
        return None
    if subcommand in GIT_PUBLICATION:
        return (
            f"Git {subcommand.title()} is a separate publication operation; "
            "it is not an ordinary autonomous project command"
        )
    if subcommand in GIT_DESTRUCTIVE or _force_push(subcommand, rest):
        return "destructive or history-rewriting SCM operation is a hard boundary"
    if subcommand in GIT_PATH_MUTATION:
        return _governance_mutation_boundary(
            ["git", *rest], host_root, consume_descendants=True
        )
    return None


def _git_subcommand(argv: list[str]) -> tuple[str, list[str]]:
    i = 1
    while i < len(argv):
        token = argv[i]
        if token == "--":
            i += 1
            break
        if token.startswith("-"):
            name = token.split("=", 1)[0]
            if name in GIT_GLOBAL_VALUE_FLAGS and "=" not in token:
                i += 2
                continue
            i += 1
            continue
        return token.lower(), argv[i + 1 :]
    if i < len(argv):
        return argv[i].lower(), argv[i + 1 :]
    return "", []


def _force_push(subcommand: str, rest: list[str]) -> bool:
    if subcommand != "push":
        return False
    joined = {item.lower() for item in rest}
    return bool(joined & {"--force", "--force-with-lease", "-f"})


def _git_dir_outside_workspace(argv: list[str], host_root: Path) -> str | None:
    i = 1
    while i < len(argv):
        token = argv[i]
        name = token.split("=", 1)[0]
        value = ""
        if token.startswith("--git-dir=") or token.startswith("--work-tree="):
            value = token.split("=", 1)[1]
        elif name in {"-C", "--git-dir", "--work-tree"} and i + 1 < len(argv):
            value = argv[i + 1]
            i += 2
            if value and not _path_under_host(value, host_root):
                return f"{value} is outside the project/workspace authority boundary"
            continue
        if value and not _path_under_host(value, host_root):
            return f"{value} is outside the project/workspace authority boundary"
        i += 1
    return None


def _deletion_hard_boundary(argv: list[str], host_root: Path) -> str | None:
    recursive = _is_recursive_delete(argv)
    for token in argv[1:]:
        lowered = token.lower()
        if token.startswith("-") or lowered in {"/s", "/q", "/s/q", "/f"}:
            continue
        if _token_is_protected_governance(
            token, host_root, consume_descendants=recursive
        ):
            return (
                "protected Scaffold governance or SCM deletion is a hard boundary"
            )
        if _is_filesystem_root_token(token):
            return "irrecoverable destructive deletion is a hard boundary"
        if _path_like_token(token) and not _path_under_host(token, host_root):
            return f"{token} is outside the project/workspace authority boundary"
        if recursive and token in {".", "./", ".\\"}:
            return "irrecoverable destructive deletion is a hard boundary"
    return None


def _outside_workspace_argument(argv: list[str], host_root: Path) -> str | None:
    for token in argv[1:]:
        if not _path_like_token(token):
            continue
        if path_operand_has_glob(token):
            operand = normalize_path_operand(token)
            if not operand or operand == ".." or operand.startswith("../"):
                return (
                    f"{token} is outside the project/workspace authority boundary"
                )
            continue
        if _path_under_host(token, host_root):
            continue
        return f"{token} is outside the project/workspace authority boundary"
    return None


def _governance_mutation_boundary(
    argv: list[str],
    host_root: Path,
    *,
    consume_descendants: bool = False,
) -> str | None:
    for token in argv[1:]:
        if token.startswith("-") and not _path_like_token(token):
            continue
        if _token_is_protected_governance(
            token, host_root, consume_descendants=consume_descendants
        ):
            return (
                "protected Scaffold governance or SCM mutation is a hard boundary"
            )
    return None


def _relative_executable_escape(token: str, host_root: Path) -> bool:
    if not _contains_dotdot(token):
        return False
    return not _path_under_host(token, host_root)


def _path_like_token(token: str) -> bool:
    raw = str(token or "").strip().strip('"')
    if not raw or raw.startswith("-"):
        return False
    if _looks_absolute(raw):
        return True
    if raw in {".", "..", "./", "../", ".\\", "..\\"}:
        return True
    if raw.startswith("../") or raw.startswith("..\\"):
        return True
    if raw.startswith("./") or raw.startswith(".\\"):
        return True
    if raw == "~" or raw.startswith("~/") or raw.startswith("~\\"):
        return True
    if "/" in raw or "\\" in raw:
        return True
    if path_operand_has_glob(raw):
        return True
    return _contains_dotdot(raw)


def _contains_dotdot(token: str) -> bool:
    parts = str(token or "").replace("\\", "/").split("/")
    return ".." in parts


def _operation_consumes_descendants(name: str, argv: list[str]) -> bool:
    if name in DIRECTORY_RELOCATION_NAMES or name in DIRECTORY_REMOVE_NAMES:
        return True
    return name in DELETE_NAMES and _is_recursive_delete(argv)


def _token_is_protected_governance(
    token: str,
    host_root: Path,
    *,
    consume_descendants: bool = False,
) -> bool:
    raw = str(token or "").strip().strip('"')
    if not raw:
        return False
    if raw.startswith("-") and not _path_like_token(raw):
        return False
    if Path(raw.replace("\\", "/")).name in {".scaffold", ".git"}:
        return True
    operand = raw
    if not path_operand_has_glob(raw):
        relative = _host_relative_posix(raw, host_root)
        if relative:
            operand = relative
    return path_operand_selects_protected_authority(
        host_root,
        operand,
        consume_descendants=consume_descendants,
    )


def _host_relative_posix(token: str, host_root: Path) -> str | None:
    raw = str(token or "").strip().strip('"')
    if not raw:
        return None
    try:
        candidate = Path(raw)
        if raw.startswith("~"):
            candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            candidate = host_root / candidate
        resolved = candidate.resolve()
        return resolved.relative_to(host_root).as_posix()
    except (OSError, ValueError):
        return None


def _is_filesystem_root_token(token: str) -> bool:
    raw = str(token or "").strip()
    if raw in {"/", "~", "~/", "..", "../"}:
        return True
    if len(raw) == 3 and raw[1] == ":" and raw[2] in {"\\", "/"}:
        return True
    if len(raw) == 2 and raw[1] == ":":
        return True
    return False


def _is_recursive_delete(argv: list[str]) -> bool:
    tokens = {item.lower() for item in argv[1:]}
    return bool(
        tokens
        & {
            "-r",
            "-rf",
            "-fr",
            "-rfo",
            "--recursive",
            "/s",
            "-recurse",
            "-r:true",
        }
    )


def _has_flag(argv: list[str], names: set[str]) -> bool:
    wanted = {name.lower() for name in names}
    for token in argv[1:]:
        name = token.split("=", 1)[0].lower()
        if name in wanted:
            return True
    return False


def _looks_absolute(token: str) -> bool:
    raw = str(token or "").strip().strip('"')
    if not raw or raw.startswith("-"):
        return False
    path = Path(raw)
    if path.is_absolute():
        return True
    return len(raw) >= 3 and raw[1] == ":" and raw[2] in {"\\", "/"}


def _path_under_host(token: str, host_root: Path) -> bool:
    raw = str(token or "").strip().strip('"')
    if not raw:
        return False
    try:
        candidate = Path(raw)
        if raw.startswith("~"):
            candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            candidate = host_root / candidate
        resolved = candidate.resolve()
        resolved.relative_to(host_root)
        return True
    except (OSError, ValueError):
        return False
