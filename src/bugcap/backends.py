"""Capture backends: detection, install suggestions and (opt-in) installation, per OS."""
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


def platform_key() -> str:
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


# Windows binaries known to install outside PATH with no fallback shim: their installer is a
# plain MSI/WiX package with no winget "Commands" entry, so neither the installer nor winget
# ever registers them on PATH (unlike scoop/choco, which always add their own shim dir, or
# winget's own "portable" installer type, which winget manages the PATH entry for itself).
# Checked against this project's other backends: satty/grim/wf-recorder are Linux-only and
# screencapture is macOS-only, so this table only needs Windows-only entries.
_WINDOWS_FALLBACK_DIRS: dict[str, list[tuple[str, ...]]] = {
    "flameshot": [("Flameshot", "bin")],
}


def _windows_fallback_candidates(name: str) -> list[Path]:
    # Path parts, not a single string: on CI, tests simulate "windows" by monkeypatching
    # sys.platform while pathlib.Path stays bound to the real (often POSIX) OS, which would
    # treat a literal "Flameshot\bin" as one oddly-named component instead of two.
    rel_parts_list = _WINDOWS_FALLBACK_DIRS.get(name, [])
    roots = [os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")]
    return [Path(root, *rel_parts) for root in roots if root for rel_parts in rel_parts_list]


def resolve(name: str) -> Optional[str]:
    """Full path to the `name` executable: PATH first, then (on Windows) known install
    locations for binaries whose installer never touches PATH. Use this instead of
    `shutil.which` directly so a capture/record backend can actually be launched, not just
    detected.
    """
    found = shutil.which(name)
    if found:
        return found
    if platform_key() != "windows":
        return None
    for directory in _windows_fallback_candidates(name):
        candidate = directory / f"{name}.exe"
        if candidate.is_file():
            return str(candidate)
    return None


def ensure_on_user_path(name: str) -> None:
    """If `name` was only found via a fallback install location (not already on PATH),
    persist that directory to the user's PATH registry so later shells and tools - not just
    bugcap - can find it without needing the fallback. Best-effort: any failure is silent,
    since `resolve()` already makes bugcap itself work without this.
    """
    if platform_key() != "windows" or shutil.which(name):
        return
    resolved = resolve(name)
    if not resolved:
        return
    directory = str(Path(resolved).parent)
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_READ | winreg.KEY_SET_VALUE
        ) as key:
            try:
                current, kind = winreg.QueryValueEx(key, "Path")
            except FileNotFoundError:
                current, kind = "", winreg.REG_EXPAND_SZ
            parts = [p for p in current.split(os.pathsep) if p]
            if any(p.lower() == directory.lower() for p in parts):
                return
            parts.append(directory)
            winreg.SetValueEx(key, "Path", 0, kind, os.pathsep.join(parts))
        os.environ["PATH"] = os.environ.get("PATH", "") + os.pathsep + directory
    except OSError:
        pass


@dataclass
class Backend:
    name: str
    binaries: list[str]  # every one must be resolvable (PATH, or a known fallback location)
    description: str
    platforms: tuple[str, ...]
    annotates: bool
    # platform -> [(package manager binary, argv)]
    installs: dict[str, list[tuple[str, list[str]]]] = field(default_factory=dict)
    manual: dict[str, str] = field(default_factory=dict)  # platform -> guidance

    def available(self) -> bool:
        if platform_key() not in self.platforms:
            return False
        return all(resolve(b) for b in self.binaries)


BACKENDS = [
    Backend(
        name="flameshot",
        binaries=["flameshot"],
        description="Cross-platform capture + annotation UI (recommended everywhere)",
        platforms=("linux", "macos", "windows"),
        annotates=True,
        installs={
            "linux": [
                ("apt-get", ["apt-get", "install", "-y", "flameshot"]),
                ("dnf", ["dnf", "install", "-y", "flameshot"]),
                ("pacman", ["pacman", "-S", "--noconfirm", "flameshot"]),
                ("zypper", ["zypper", "install", "-y", "flameshot"]),
                ("brew", ["brew", "install", "flameshot"]),
            ],
            "macos": [("brew", ["brew", "install", "--cask", "flameshot"])],
            "windows": [
                ("winget", ["winget", "install", "--id", "Flameshot.Flameshot", "-e"]),
                ("scoop", ["scoop", "install", "flameshot"]),
                ("choco", ["choco", "install", "-y", "flameshot"]),
            ],
        },
        manual={
            "linux": "See https://flameshot.org/docs/installation/",
            "macos": "brew install --cask flameshot, or https://flameshot.org/#download",
            "windows": "winget install Flameshot.Flameshot, or https://flameshot.org/#download",
        },
    ),
    Backend(
        name="satty",
        binaries=["satty", "grim"],
        description="Wayland-native annotation (needs grim for the grab)",
        platforms=("linux",),
        annotates=True,
        installs={
            "linux": [
                ("pacman", ["pacman", "-S", "--noconfirm", "satty", "grim"]),
                ("brew", ["brew", "install", "satty"]),
            ]
        },
        manual={
            "linux": "Install grim from your distro, and satty from "
            "https://github.com/Satty-org/Satty (or `cargo install satty`)",
        },
    ),
    Backend(
        name="screencapture",
        binaries=["screencapture"],
        description="macOS built-in region capture (no annotation)",
        platforms=("macos",),
        annotates=False,
        manual={"macos": "Built in to macOS; nothing to install."},
    ),
]


def by_name(name: str) -> Backend:
    for backend in BACKENDS:
        if backend.name == name:
            return backend
    raise KeyError(name)


def _sync_path_from_registry() -> None:
    """Pick up a freshly-installed Windows tool without a new terminal.

    winget/scoop/choco update the user/machine PATH in the registry, but an
    already-running process (and any shell that was already open when the
    install happened) keeps its original PATH until it restarts. That made
    `bugcap live` report "No capture tool found" right after `bugcap setup`
    had just installed flameshot in the same session. Re-reading PATH from
    the registry before every detection closes that gap. Best-effort: any
    failure here just leaves PATH as-is.
    """
    if sys.platform != "win32":
        return
    try:
        import winreg
    except ImportError:
        return
    try:
        chunks = [os.environ.get("PATH", "")]
        for hive, subkey in (
            (winreg.HKEY_CURRENT_USER, r"Environment"),
            (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
        ):
            try:
                with winreg.OpenKey(hive, subkey) as key:
                    value, _ = winreg.QueryValueEx(key, "Path")
                    chunks.append(value)
            except OSError:
                continue
        seen = set()
        merged = []
        for chunk in chunks:
            for part in chunk.split(os.pathsep):
                key = part.lower()
                if part and key not in seen:
                    seen.add(key)
                    merged.append(part)
        os.environ["PATH"] = os.pathsep.join(merged)
    except OSError:
        pass


def detect() -> Optional[Backend]:
    """First available backend, in preference order."""
    _sync_path_from_registry()
    return next((b for b in BACKENDS if b.available()), None)


def recommended() -> Backend:
    """What to suggest installing on this OS. Flameshot is cross-platform and annotates,
    so it is the recommendation on every supported OS (satty is the Wayland alternative)."""
    return by_name("flameshot")


def install_command(backend: Backend) -> Optional[list[str]]:
    """Full argv (with sudo when needed) for the first usable package manager, or None."""
    for manager, argv in backend.installs.get(platform_key(), []):
        if not shutil.which(manager):
            continue
        needs_root = manager in {"apt-get", "dnf", "pacman", "zypper"}
        if needs_root and hasattr(os, "geteuid") and os.geteuid() != 0:
            if not shutil.which("sudo"):
                continue
            return ["sudo", *argv]
        return list(argv)
    return None


def guidance(backend: Backend) -> str:
    return backend.manual.get(platform_key(), "See the project's website for install steps.")


def install(backend: Backend) -> int:
    cmd = install_command(backend)
    if cmd is None:
        raise RuntimeError(
            f"No supported package manager found for {backend.name}. {guidance(backend)}"
        )
    return subprocess.run(cmd).returncode
