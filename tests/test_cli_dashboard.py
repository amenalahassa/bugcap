import pytest

from bugcap import cli
from bugcap.dashboard import server as srv


@pytest.fixture
def captured(monkeypatch):
    calls = {}

    def fake_serve(host="127.0.0.1", port=8765, open_browser=False, explicit_host=False):
        calls.update(host=host, port=port, open=open_browser, explicit=explicit_host)

    monkeypatch.setattr(srv, "serve", fake_serve)
    return calls


def test_defaults_bind_loopback(captured):
    assert cli.main(["dashboard"]) == 0
    assert captured == dict(host="127.0.0.1", port=8765, open=False, explicit=False)


def test_explicit_non_loopback_warns(captured, capsys):
    assert cli.main(["dashboard", "--host", "0.0.0.0", "--port", "0", "--open"]) == 0
    assert "warning: dashboard exposed on 0.0.0.0; anyone on that network can read and edit your bugs" in capsys.readouterr().err
    assert captured == dict(host="0.0.0.0", port=0, open=True, explicit=True)


def test_explicit_loopback_no_warning(captured, capsys):
    cli.main(["dashboard", "--host", "localhost"])
    assert capsys.readouterr().err == ""


def test_serve_refuses_non_loopback_without_flag():
    with pytest.raises(ValueError):
        srv.serve(host="0.0.0.0")


def test_port_zero_prints_chosen_url(bugcap_home, monkeypatch, capsys):
    def stop(self, *a, **k):
        raise KeyboardInterrupt

    monkeypatch.setattr(srv.DashboardServer, "serve_forever", stop)
    srv.serve(port=0)
    out = capsys.readouterr().out
    assert out.startswith("bugcap dashboard: http://127.0.0.1:") and ":0/" not in out
