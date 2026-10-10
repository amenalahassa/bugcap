"""T011: backend detection, recommendation, install-command and guidance per simulated OS."""

import sys

import pytest

from bugcap import backends

_needs_winreg = pytest.mark.skipif(sys.platform != "win32", reason="winreg is a Windows-only stdlib module")


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


def test_sync_path_from_registry_is_noop_off_windows(monkeypatch):
    monkeypatch.setattr(backends.sys, "platform", "linux")
    before = backends.os.environ.get("PATH")
    backends._sync_path_from_registry()
    assert backends.os.environ.get("PATH") == before


@_needs_winreg
def test_sync_path_from_registry_merges_and_dedupes(monkeypatch):
    """A tool winget just installed updates the registry's PATH, but this already-running
    process keeps its stale PATH until re-synced -- which is why `bugcap live` could say
    "No capture tool found" right after `bugcap setup` had just installed flameshot."""
    import winreg

    monkeypatch.setattr(backends.sys, "platform", "win32")
    monkeypatch.setenv("PATH", r"C:\Existing")

    class FakeKey:
        def __init__(self, value):
            self.value = value

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_open_key(hive, subkey):
        if hive == winreg.HKEY_CURRENT_USER:
            return FakeKey(r"C:\NewTool;C:\Existing")
        raise OSError("not simulated")

    monkeypatch.setattr(winreg, "OpenKey", fake_open_key)
    monkeypatch.setattr(winreg, "QueryValueEx", lambda key, name: (key.value, 1))

    backends._sync_path_from_registry()

    parts = backends.os.environ["PATH"].split(backends.os.pathsep)
    assert parts.count(r"C:\Existing") == 1  # deduped, not doubled
    assert r"C:\NewTool" in parts


@_needs_winreg
def test_sync_path_from_registry_survives_registry_errors(monkeypatch):
    import winreg

    monkeypatch.setattr(backends.sys, "platform", "win32")
    monkeypatch.setenv("PATH", r"C:\Existing")
    monkeypatch.setattr(winreg, "OpenKey", lambda hive, subkey: (_ for _ in ()).throw(OSError("denied")))
    backends._sync_path_from_registry()  # must not raise
    assert backends.os.environ["PATH"] == r"C:\Existing"


# --- resolve(): fallback for installers that never touch PATH (bugcap report #1) -------------


def test_resolve_prefers_path_over_fallback(monkeypatch):
    monkeypatch.setattr(backends.sys, "platform", "win32")
    monkeypatch.setattr(backends.shutil, "which", lambda b: "C:/on/path/" + b)
    assert backends.resolve("flameshot") == "C:/on/path/flameshot"


def test_resolve_falls_back_to_known_windows_install_dir(monkeypatch, tmp_path):
    """Flameshot's Windows package is a plain MSI with no winget shim, so after
    `winget install Flameshot.Flameshot` it sits in Program Files but is never on PATH."""
    monkeypatch.setattr(backends.sys, "platform", "win32")
    monkeypatch.setattr(backends.shutil, "which", lambda b: None)
    program_files = tmp_path / "Program Files"
    flameshot_dir = program_files / "Flameshot" / "bin"
    flameshot_dir.mkdir(parents=True)
    exe = flameshot_dir / "flameshot.exe"
    exe.write_text("")
    monkeypatch.setenv("ProgramFiles", str(program_files))
    monkeypatch.delenv("ProgramFiles(x86)", raising=False)
    assert backends.resolve("flameshot") == str(exe)


def test_resolve_none_when_not_on_path_and_no_fallback_hit(monkeypatch, tmp_path):
    monkeypatch.setattr(backends.sys, "platform", "win32")
    monkeypatch.setattr(backends.shutil, "which", lambda b: None)
    monkeypatch.setenv("ProgramFiles", str(tmp_path))  # empty: no Flameshot\bin inside
    monkeypatch.delenv("ProgramFiles(x86)", raising=False)
    assert backends.resolve("flameshot") is None


def test_resolve_fallback_is_windows_only(monkeypatch, tmp_path):
    monkeypatch.setattr(backends.sys, "platform", "linux")
    monkeypatch.setattr(backends.shutil, "which", lambda b: None)
    flameshot_dir = tmp_path / "Flameshot" / "bin"
    flameshot_dir.mkdir(parents=True)
    (flameshot_dir / "flameshot.exe").write_text("")
    monkeypatch.setenv("ProgramFiles", str(tmp_path))
    assert backends.resolve("flameshot") is None


def test_available_uses_fallback_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(backends.sys, "platform", "win32")
    monkeypatch.setattr(backends.shutil, "which", lambda b: None)
    flameshot_dir = tmp_path / "Flameshot" / "bin"
    flameshot_dir.mkdir(parents=True)
    (flameshot_dir / "flameshot.exe").write_text("")
    monkeypatch.setenv("ProgramFiles", str(tmp_path))
    monkeypatch.delenv("ProgramFiles(x86)", raising=False)
    assert backends.by_name("flameshot").available() is True


# --- ensure_on_user_path(): persist a fallback dir so other tools find it too ----------------


def test_ensure_on_user_path_noop_off_windows(monkeypatch):
    monkeypatch.setattr(backends.sys, "platform", "linux")
    backends.ensure_on_user_path("flameshot")  # must not raise


@_needs_winreg
def test_ensure_on_user_path_noop_when_already_on_path(monkeypatch):
    import winreg

    monkeypatch.setattr(backends.sys, "platform", "win32")
    monkeypatch.setattr(backends.shutil, "which", lambda b: "C:/already/" + b)
    monkeypatch.setattr(
        winreg, "OpenKey", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not open registry"))
    )
    backends.ensure_on_user_path("flameshot")  # returns before touching the registry


@_needs_winreg
def test_ensure_on_user_path_adds_fallback_dir(monkeypatch, tmp_path):
    import winreg

    monkeypatch.setattr(backends.sys, "platform", "win32")
    monkeypatch.setattr(backends.shutil, "which", lambda b: None)
    # ensure_on_user_path updates os.environ["PATH"] directly (that's the point: the running
    # process should pick up the fallback dir immediately) -- pre-register it with monkeypatch
    # so that direct write is still undone at teardown, instead of leaking into later tests.
    monkeypatch.setenv("PATH", backends.os.environ.get("PATH", ""))
    flameshot_dir = tmp_path / "Flameshot" / "bin"
    flameshot_dir.mkdir(parents=True)
    (flameshot_dir / "flameshot.exe").write_text("")
    monkeypatch.setenv("ProgramFiles", str(tmp_path))
    monkeypatch.delenv("ProgramFiles(x86)", raising=False)

    written = {}

    class FakeKey:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(winreg, "OpenKey", lambda hive, subkey, reserved, access: FakeKey())
    monkeypatch.setattr(
        winreg, "QueryValueEx", lambda key, name: (_ for _ in ()).throw(FileNotFoundError())
    )

    def fake_set(key, name, reserved, kind, value):
        written["value"] = value
        written["kind"] = kind

    monkeypatch.setattr(winreg, "SetValueEx", fake_set)

    backends.ensure_on_user_path("flameshot")

    assert str(flameshot_dir) in written["value"].split(backends.os.pathsep)
    assert written["kind"] == winreg.REG_EXPAND_SZ
    assert backends.os.environ["PATH"].endswith(str(flameshot_dir))


@_needs_winreg
def test_ensure_on_user_path_dedupes_existing_entry(monkeypatch, tmp_path):
    import winreg

    monkeypatch.setattr(backends.sys, "platform", "win32")
    monkeypatch.setattr(backends.shutil, "which", lambda b: None)
    flameshot_dir = tmp_path / "Flameshot" / "bin"
    flameshot_dir.mkdir(parents=True)
    (flameshot_dir / "flameshot.exe").write_text("")
    monkeypatch.setenv("ProgramFiles", str(tmp_path))
    monkeypatch.delenv("ProgramFiles(x86)", raising=False)

    class FakeKey:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(winreg, "OpenKey", lambda hive, subkey, reserved, access: FakeKey())
    monkeypatch.setattr(winreg, "QueryValueEx", lambda key, name: (str(flameshot_dir), 2))
    set_calls = []
    monkeypatch.setattr(winreg, "SetValueEx", lambda *a: set_calls.append(a))

    backends.ensure_on_user_path("flameshot")

    assert set_calls == []  # already there: must not write a duplicate


@_needs_winreg
def test_ensure_on_user_path_survives_registry_errors(monkeypatch, tmp_path):
    import winreg

    monkeypatch.setattr(backends.sys, "platform", "win32")
    monkeypatch.setattr(backends.shutil, "which", lambda b: None)
    flameshot_dir = tmp_path / "Flameshot" / "bin"
    flameshot_dir.mkdir(parents=True)
    (flameshot_dir / "flameshot.exe").write_text("")
    monkeypatch.setenv("ProgramFiles", str(tmp_path))
    monkeypatch.delenv("ProgramFiles(x86)", raising=False)
    monkeypatch.setattr(
        winreg, "OpenKey", lambda *a: (_ for _ in ()).throw(OSError("denied"))
    )
    backends.ensure_on_user_path("flameshot")  # must not raise
