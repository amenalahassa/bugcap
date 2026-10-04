"""Capture backends: detection, install suggestions and (opt-in) installation, per OS."""
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Optional


def platform_key() -> str:
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


@dataclass
class Backend:
    name: str
    binaries: list[str]  # every one must be on PATH
    description: str
    platforms: tuple[str, ...]
    annotates: bool
    # platform -> [(package manager binary, argv)]
    installs: dict[str, list[tuple[str, list[str]]]] = field(default_factory=dict)
    manual: dict[str, str] = field(default_factory=dict)  # platform -> guidance

    def available(self) -> bool:
        if platform_key() not in self.platforms:
            return False
        return all(shutil.which(b) for b in self.binaries)


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


def detect() -> Optional[Backend]:
    """First available backend, in preference order."""
    return next((b for b in BACKENDS if b.available()), None)


def recommended() -> Backend:
    """What to suggest installing on this OS."""
    if platform_key() == "linux" and os.environ.get("XDG_SESSION_TYPE") == "wayland":
        return by_name("flameshot")  # works on most compositors; satty is the alternative
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
