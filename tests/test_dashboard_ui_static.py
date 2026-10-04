import re
from importlib import resources

BASE = resources.files("bugcap.dashboard") / "static"


def _text(name):
    return (BASE / name).read_text()


def test_viewport_and_both_themes():
    assert 'name="viewport"' in _text("index.html")
    css = _text("app.css")
    assert "prefers-color-scheme: dark" in css and ':root[data-theme="dark"]' in css
    assert re.search(r"body\s*{[^}]*background", css)  # explicit page background


def test_no_fixed_width_wider_than_phone():
    css = _text("app.css")
    for match in re.finditer(r"(?<!max-)(?<!min-)width:\s*(\d+)px", css):
        assert int(match.group(1)) <= 360
    assert "min-width" not in css or all(int(n) <= 360 for n in re.findall(r"min-width:\s*(\d+)px", css))
    assert re.search(r"minmax\(\s*(\d+)px", css) and int(re.search(r"minmax\(\s*(\d+)px", css).group(1)) <= 200
    assert "max-width: 100%" in css  # media never overflows
