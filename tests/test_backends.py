"""T011: backend detection, recommendation, install-command and guidance per simulated OS."""
import os

import pytest

from bugcap import backends


@pytest.mark.parametrize(
    "platform,key",
    [("linux", "linux"), ("linux2", "linux"), ("darwin", "macos"), ("win32", "windows")],
)
def test_platform_key(monkeypatch, platform, key):
    monkeypatch.setattr(backends.sys, "platform", platform)
    assert backends.platform_key() == key


def test_detect_prefers_flameshot(monkeypatch):
    monkeypatch.setattr(backends.sys, "platform", "linux")
    monkeypatch.setattr(backends.shutil, "which", lambda b: "/usr/bin/" + b)  # all present
    assert backends.detect().name == "flameshot"


def test_detect_none_when_nothing_present(monkeypatch):
    monkeypatch.setattr(backends.sys, "platform", "linux")
    monkeypatch.setattr(backends.shutil, "which", lambda b: None)
    assert backends.detect() is None


@pytest.mark.parametrize("platform", ["linux", "darwin", "win32"])
def test_recommended_per_os(monkeypatch, platform):
    monkeypatch.setattr(backends.sys, "platform", platform)
    rec = backends.recommended()
    assert rec.name == "flameshot"
    assert backends.platform_key() in rec.platforms


def test_install_command_picks_first_available_with_sudo(monkeypatch):
    monkeypatch.setattr(backends.sys, "platform", "linux")
    # Only dnf present (apt-get missing), plus sudo.
    present = {"dnf", "sudo"}
    monkeypatch.setattr(backends.shutil, "which", lambda b: ("/usr/bin/" + b) if b in present else None)
    monkeypatch.setattr(backends.os, "geteuid", lambda: 1000, raising=False)
    cmd = backends.install_command(backends.by_name("flameshot"))
    assert cmd == ["sudo", "dnf", "install", "-y", "flameshot"]


def test_install_command_no_sudo_when_root(monkeypatch):
    monkeypatch.setattr(backends.sys, "platform", "linux")
    monkeypatch.setattr(backends.shutil, "which", lambda b: "/usr/bin/" + b)
    monkeypatch.setattr(backends.os, "geteuid", lambda: 0, raising=False)
    cmd = backends.install_command(backends.by_name("flameshot"))
    assert cmd[0] != "sudo"
    assert cmd[:2] == ["apt-get", "install"]


def test_install_command_windows_no_geteuid(monkeypatch):
    monkeypatch.setattr(backends.sys, "platform", "win32")
    present = {"winget"}
    monkeypatch.setattr(backends.shutil, "which", lambda b: ("C:/" + b) if b in present else None)
    # Simulate absence of geteuid as on Windows.
    monkeypatch.delattr(backends.os, "geteuid", raising=False)
    cmd = backends.install_command(backends.by_name("flameshot"))
    assert cmd[0] == "winget"


def test_install_command_none_without_manager(monkeypatch):
    monkeypatch.setattr(backends.sys, "platform", "linux")
    monkeypatch.setattr(backends.shutil, "which", lambda b: None)
    assert backends.install_command(backends.by_name("flameshot")) is None


@pytest.mark.parametrize("platform", ["linux", "darwin", "win32"])
def test_guidance_per_os(monkeypatch, platform):
    monkeypatch.setattr(backends.sys, "platform", platform)
    text = backends.guidance(backends.by_name("flameshot"))
    assert text and "flameshot" in text.lower()
