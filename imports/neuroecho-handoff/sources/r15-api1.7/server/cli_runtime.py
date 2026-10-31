"""Resolve installed CLIs for a desktop app launched outside a shell.

The web service is local on both Windows and macOS.  Finder/Explorer launches
do not inherit the user's interactive shell PATH, and npm CLIs may be exposed
as ``.cmd`` shims on Windows.  Keep all executable discovery here so source
adapters do not grow platform-specific path lists of their own.
"""
import os
import shutil
from pathlib import Path


def _roots() -> list[Path]:
    home = Path.home()
    roots = [
        home / ".local" / "bin",
        home / ".nianxiang" / "tools" / "bin",
        home / ".nianxiang" / "tools" / "node_modules" / ".bin",
    ]
    if os.name == "nt":
        local = Path(os.environ.get("LOCALAPPDATA", str(home / "AppData" / "Local")))
        roaming = Path(os.environ.get("APPDATA", str(home / "AppData" / "Roaming")))
        roots.extend([
            local / "Programs" / "Python" / "Scripts",
            local / "Programs" / "nodejs",
            roaming / "npm",
            home / "AppData" / "Local" / "Microsoft" / "WinGet" / "Links",
        ])
    else:
        roots.extend([Path("/opt/homebrew/bin"), Path("/usr/local/bin"), Path("/usr/bin")])
    return roots


def _candidate_names(name: str) -> list[str]:
    if os.name != "nt" or Path(name).suffix.lower() in {".exe", ".cmd", ".bat", ".com"}:
        return [name]
    return [name, f"{name}.exe", f"{name}.cmd", f"{name}.bat"]


def _is_executable(path: Path) -> bool:
    return path.is_file() and (os.name == "nt" or os.access(path, os.X_OK))


def command(name: str, override: str | None = None) -> list[str] | None:
    """Return an argv prefix safe for native binaries and Windows shims."""
    path = resolve(name, override)
    if not path:
        return None
    suffix = Path(path).suffix.lower()
    if os.name == "nt" and suffix in {".cmd", ".bat"}:
        comspec = os.environ.get("ComSpec") or os.environ.get("COMSPEC") or "cmd.exe"
        return [comspec, "/d", "/s", "/c", path]
    return [path]


def command_for_path(path: str) -> list[str]:
    """Wrap a path returned by a mocked or already-resolved executable."""
    suffix = Path(path).suffix.lower()
    if os.name == "nt" and suffix in {".cmd", ".bat"}:
        comspec = os.environ.get("ComSpec") or os.environ.get("COMSPEC") or "cmd.exe"
        return [comspec, "/d", "/s", "/c", path]
    return [path]


def resolve(name, override=None):
    explicit = os.getenv(override, "").strip() if override else ""
    if explicit:
        # An explicit command may be a PATH name (useful for ``gh.exe``) or a
        # full path.  Never silently fall back to another executable when an
        # explicitly configured path is stale.
        explicit_path = Path(explicit).expanduser()
        if explicit_path.is_file():
            return str(explicit_path)
        return shutil.which(explicit) or None
    found = shutil.which(name)
    if found:
        return found
    for root in _roots():
        for candidate_name in _candidate_names(name):
            candidate = root / candidate_name
            if _is_executable(candidate):
                return str(candidate)
    return None


def environment():
    env = os.environ.copy()
    # npm shims need Node even if the service was started from Finder or
    # Explorer.  Keep the inherited PATH first so the user's selected version
    # wins, then append known user and system locations.
    # Keep macOS locations in PATH even when tests or a managed launcher
    # emulate another platform; they are harmless on Windows and make the
    # generated environment deterministic across launch methods.
    extra = [str(root) for root in _roots()]
    if os.name == "nt":
        extra.extend(["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin"])
    env["PATH"] = os.pathsep.join([value for value in [env.get("PATH", ""), *extra] if value])
    env.update(NO_COLOR="1", FORCE_HYPERLINK="0", GH_PROMPT_DISABLED="1")
    return env


def probe(name: str, override: str | None = None) -> dict:
    """Return safe installation metadata without invoking the command."""
    path = resolve(name, override)
    if path:
        return {"installed": True, "path": path}
    return {"installed": False, "path": ""}
