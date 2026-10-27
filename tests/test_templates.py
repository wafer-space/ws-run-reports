"""The run page's list of which designs use something: every name shown, full-colour names before faded ones."""

import re
from types import SimpleNamespace

from ws_run_reports.site import template_environment


def _macros(tt=None):
    env = template_environment()
    context = {"tt": tt, "design_href": lambda code: f"projects/{code}.html"}
    return env.get_template("_names.html").make_module(context)


def _design(code, ip_only=()):
    return SimpleNamespace(code=code, name=f"Design {code}", ip_sources={key: ["block"] for key in ip_only},
                           ip_only=lambda key: key in ip_only)


def _names(html):
    return re.findall(r">Design (\w+)(?:<span[^>]*>[^<]*</span>)?</a>", html)


def test_who_shows_every_name_without_a_toggle():
    users = [_design(f"D{i:02}") for i in range(30)]
    html = str(_macros().who(users))
    assert _names(html) == [u.code for u in users]
    assert "<details" not in html and "<summary" not in html


def test_who_separates_the_names_with_commas():
    html = str(_macros().who([_design("A1"), _design("B2"), _design("C3")]))
    assert html.count("</a>, <a") == 2
    assert not html.startswith(",") and not html.rstrip().endswith(",")


def test_who_puts_faded_names_last_keeping_each_groups_order():
    users = [_design("A1", ip_only=["mim"]), _design("B2"), _design("C3", ip_only=["mim"]), _design("D4")]
    html = str(_macros().who(users, "mim"))
    assert _names(html) == ["B2", "D4", "A1", "C3"]
    assert html.count("</a>, <a") == 3
    assert html.count('class="run-ip-only"') == 2
    assert 'title="Only inside reused block"' in html
    assert html.count('<span class="run-sr-only">, only inside reused block</span>') == 2


def test_who_escapes_names_and_blocks():
    design = SimpleNamespace(code="A1", name="R&D <test>", ip_sources={"mim": ["a<b"]}, ip_only=lambda key: True)
    html = str(_macros().who([design], "mim"))
    assert "R&amp;D &lt;test&gt;" in html and "<test>" not in html
    assert 'title="Only inside reused a&lt;b"' in html


def test_who_without_a_device_fades_nothing():
    users = [_design("A1", ip_only=["mim"]), _design("B2")]
    html = str(_macros().who(users))
    assert _names(html) == ["A1", "B2"]
    assert "run-ip-only" not in html
