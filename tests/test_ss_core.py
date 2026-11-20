import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import ss_core as core  # noqa: E402

FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def load(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return json.load(f)


def test_parse_clean_report():
    r = load("report_clean.json")
    assert core.parse_findings(r) == []
    assert core.risk_summary(r)[0] == "SAFE"
    assert core.verdict(core.count_by_severity([]), "SAFE")[2] == "ok"


def test_parse_risky_report():
    r = load("report_risky.json")
    f = core.parse_findings(r)
    assert len(f) == 17
    assert f[0]["severity"] == "High"  # sorted, worst first
    assert all(x["title"] and x["description"] for x in f)
    assert any(x["where"].startswith("scripts/setup.py · line") for x in f)
    counts = core.count_by_severity(f)
    assert sum(counts.values()) == 17
    assert core.verdict(counts, core.risk_summary(r)[0])[0] == "Do not install"


def test_verdict_from_counts_without_recommendation():
    assert core.verdict({"High": 1, "Medium": 0, "Low": 0})[2] == "bad"
    assert core.verdict({"High": 0, "Medium": 2, "Low": 0})[2] == "warn"
    assert core.verdict({"High": 0, "Medium": 0, "Low": 0})[2] == "ok"


def test_incomplete_note():
    assert core.incomplete_note(load("report_clean.json")) == ""
    assert "40" in core.incomplete_note({"analysis_completeness": {"is_complete": False, "coverage_percent": 40}})


def test_unknown_format_returns_none():
    assert core.parse_findings({"hello": "world"}) is None


def test_load_json_text_tolerates_noise():
    assert core._load_json_text('warning\n{"a": 1}\n') == {"a": 1}
    assert core._load_json_text("") is None
    assert core._load_json_text("not json") is None


def test_markdown_export():
    r = load("report_risky.json")
    f = core.parse_findings(r)
    md = core.to_markdown("my-skill", f, core.count_by_severity(f), "DO_NOT_INSTALL")
    assert "Do not install" in md and "my-skill" in md


def test_validate_target(tmp_path):
    assert core.validate_target("folder", "")
    assert core.validate_target("folder", "--output=x")
    assert core.validate_target("folder", str(tmp_path)) is None
    assert core.validate_target("folder", str(tmp_path / "nope"))
    f = tmp_path / "SKILL.md"
    f.write_text("x")
    assert core.validate_target("file", str(f)) is None
    assert core.validate_target("folder", str(f))
    assert core.validate_target("git", "https://github.com/user/repo") is None
    assert core.validate_target("git", "not a link")
    assert core.validate_target("git", "-https://x")


def test_strip_ansi():
    assert core.strip_ansi("\x1b[31mred\x1b[0m") == "red"


def test_no_key_error_message(monkeypatch):
    """Without --no-llm and no key the real tool exits 2; we show a friendly message."""
    text = open(os.path.join(FIX, "nokey_error.txt"), encoding="utf-8").read()

    def fake_run_stream(cmd, on_line, holder, extra_env=None, stdout_path=None):
        for line in text.splitlines():
            on_line(line)
        open(stdout_path, "wb").close()
        return 2

    monkeypatch.setattr(core, "run_stream", fake_run_stream)
    res = core.run_scan("skillspector", "x", False, "openai", "", lambda l: None, {})
    assert not res["ok"] and "API key" in res["error"]


skillspector = core.find_skillspector()


@pytest.mark.skipif(not skillspector, reason="skillspector not installed")
def test_real_quick_scan(tmp_path):
    (tmp_path / "SKILL.md").write_text("---\nname: t\ndescription: t\n---\nCount words.\n")
    res = core.run_scan(skillspector, str(tmp_path), True, "openai", "", lambda l: None, {})
    assert res["ok"], res
    assert core.parse_findings(res["report"]) == []
