import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import ss_core as core  # noqa: E402
import ss_groups  # noqa: E402

FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def load(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------- parsing

def test_parse_clean_report():
    r = load("report_clean.json")
    assert core.parse_findings(r) == []
    assert core.risk_summary(r)[0] == "SAFE"
    assert core.verdict(core.count_by_severity([]), r)[0] == "SAFE"
    assert core.verdict(core.count_by_severity([]), r)[2] == "ok"


def test_parse_risky_report():
    r = load("report_risky.json")
    f = core.parse_findings(r)
    assert len(f) == 17
    assert f[0]["severity"] == "Critical"  # four raw levels, worst first
    assert all(x["title"] and x["description"] for x in f)
    assert any(x["where"].startswith("scripts/setup.py · line") for x in f)
    assert any(x["file"] == "scripts/setup.py" and isinstance(x["line"], int) for x in f)
    counts = core.count_by_severity(f)
    assert sum(counts.values()) == 17 and list(counts) == ["Critical", "High", "Medium", "Low"]
    assert core.verdict(counts, r)[0] == "DO_NOT_INSTALL"


def test_parse_ponytail_report():
    r = load("report_ponytail.json")
    f = core.parse_findings(r)
    assert len(f) == 109
    assert core.count_by_severity(f) == {"Critical": 1, "High": 36, "Medium": 68, "Low": 4}
    order = [x["severity"] for x in f]
    assert order == sorted(order, key=core.SEVERITIES.index)
    assert all(x["file"] for x in f)


def test_score_and_recommendation_are_exact():
    r = load("report_ponytail.json")
    assert core.risk_summary(r) == ("DO_NOT_INSTALL", 100, "CRITICAL")
    title, sub, level = core.verdict(core.count_by_severity(core.parse_findings(r)), r)
    assert title == "DO_NOT_INSTALL" and "100" in sub and "CRITICAL" in sub and level == "bad"


def test_no_made_up_safe_label():
    # no risk_assessment -> we only say the scan finished, never "safe"
    t, sub, _ = core.verdict({"Critical": 0, "High": 0, "Medium": 0, "Low": 0}, {"issues": []})
    assert t == "Scan finished" and "safe" not in (t + sub).lower()


def test_verdict_from_counts_without_report():
    assert core.verdict({"Critical": 0, "High": 1, "Medium": 0, "Low": 0})[2] == "bad"
    assert core.verdict({"Critical": 0, "High": 0, "Medium": 2, "Low": 0})[2] == "warn"
    assert core.verdict({"Critical": 0, "High": 0, "Medium": 0, "Low": 0})[2] == "ok"


def test_unknown_format_returns_none():
    assert core.parse_findings({"hello": "world"}) is None


def test_odd_fields_do_not_crash():
    weird = {"issues": [None, 5, {}, {"severity": 7, "location": "x"}, {"location": {"file": None}},
                        {"severity": "critical", "location": {"file": "a.py", "start_line": "n/a"}}]}
    f = core.parse_findings(weird)
    assert len(f) == 4
    assert f[0]["severity"] == "Critical" and f[0]["line"] is None
    groups = core.group_findings(f)
    assert sum(g["total"] for g in groups) == 4
    assert core.completeness(weird) is None
    assert core.completeness({"analysis_completeness": "oops"}) is None
    assert core.risk_summary({"risk_assessment": "oops"}) == (None, None, None)
    assert core.completeness_lines(None) == ("", "")


def test_load_json_text_tolerates_noise():
    assert core._load_json_text('warning\n{"a": 1}\n') == {"a": 1}
    assert core._load_json_text("") is None
    assert core._load_json_text("not json") is None


# ---------------------------------------------------------------- completeness

def test_completeness_partial_scan():
    info = core.completeness(load("report_ponytail.json"))
    assert info["partial"] and info["coverage"] == 81.9 and info["llm_on"] is False
    assert "bundled_execution_surface" in info["degraded"]
    warn, details = core.completeness_lines(info)
    assert warn == "Partial scan, coverage 81.9%"
    assert "AI (LLM) analysis was off" in details and "static_patterns_tool_misuse" in details


def test_completeness_full_scan():
    info = core.completeness(load("report_clean.json"))
    assert not info["partial"]
    warn, details = core.completeness_lines(info)
    assert warn == "" and "AI (LLM) analysis was off" in details


# ---------------------------------------------------------------- grouping rules

@pytest.mark.parametrize("path,group", [
    ("skills/ponytail/SKILL.md", "Skill files"),
    (".openclaw/skills/ponytail-audit/SKILL.md", "Skill files"),
    ("SKILL.md", "Skill files"),
    ("my-skill/skill.md", "Skill files"),
    ("hooks/pre-commit.sh", "Hooks and plugin manifests"),
    (".claude-plugin/plugin.json", "Hooks and plugin manifests"),
    (".opencode/plugins/x.js", "Hooks and plugin manifests"),
    (".cursor-plugin/rules.md", "Hooks and plugin manifests"),
    ("plugin.json", "Hooks and plugin manifests"),
    ("marketplace.json", "Hooks and plugin manifests"),
    ("INSTALL.md", "Install and scripts"),
    ("scripts/setup.py", "Install and scripts"),
    (".github/workflows/ci.yml", "Install and scripts"),
    ("tests/test_x.py", "Tests, benchmarks, docs and examples"),
    ("benchmarks/agentic/judge.py", "Tests, benchmarks, docs and examples"),
    ("docs/guide.md", "Tests, benchmarks, docs and examples"),
    ("examples/a.py", "Tests, benchmarks, docs and examples"),
    ("i18n/fr/README.md", "Tests, benchmarks, docs and examples"),
    ("README.md", "Tests, benchmarks, docs and examples"),
    ("README.fr.md", "Tests, benchmarks, docs and examples"),
    ("src/main.py", "Other"),
    ("contests/a.py", "Other"),          # 'tests/' must be a whole folder name
    ("", "Other"),
    (None, "Other"),
])
def test_group_for(path, group):
    assert ss_groups.group_for(path) == group


def test_group_order_first_match_wins():
    # a test inside a skill is a skill file; a script inside tests is a script (Install group is checked first)
    assert ss_groups.group_for("skills/x/tests/t.py") == "Skill files"
    assert ss_groups.group_for("tests/scripts/run.sh") == "Install and scripts"


def test_group_for_handles_windows_paths_and_case():
    assert ss_groups.group_for("Skills\\Foo\\SKILL.MD") == "Skill files"
    assert ss_groups.group_for("./Tests/a.py") == "Tests, benchmarks, docs and examples"


def test_groups_on_ponytail_report():
    f = core.parse_findings(load("report_ponytail.json"))
    groups = core.group_findings(f)
    assert [g["name"] for g in groups] == [g[0] for g in ss_groups.ALL_GROUPS]  # fixed order, empty ones included
    assert sum(g["total"] for g in groups) == 109
    for g in groups:
        order = [x["severity"] for x in g["findings"]]
        assert order == sorted(order, key=core.SEVERITIES.index)
        assert sum(g["counts"].values()) == g["total"]
    docs = next(g for g in groups if g["name"].startswith("Tests"))
    assert docs["total"] > 109 / 2
    assert "tests, benchmarks and docs" in core.group_note(groups)


def test_group_summary_and_note():
    f = [{"severity": "High", "file": "hooks/a.sh"}, {"severity": "Low", "file": "hooks/b.sh"},
         {"severity": "Medium", "file": "src/x.py"}]
    groups = core.group_findings(f)
    hooks = next(g for g in groups if g["name"].startswith("Hooks"))
    assert core.group_summary(hooks) == "2 issues (1 High, 1 Low)"
    assert core.group_summary(next(g for g in groups if g["name"] == "Skill files")) == "0 issues"
    assert core.group_note(core.group_findings([])) == ""
    assert core.group_note(core.group_findings([{"severity": "Low", "file": "a/x"}, {"severity": "Low", "file": "hooks/x"}])
                           ).startswith("Findings are spread")


# ---------------------------------------------------------------- open file / folders

def test_local_scan_root_and_resolve(tmp_path):
    (tmp_path / "skills" / "a").mkdir(parents=True)
    f = tmp_path / "skills" / "a" / "SKILL.md"
    f.write_text("x")
    assert core.local_scan_root("folder", str(tmp_path)) == str(tmp_path)
    assert core.local_scan_root("file", str(f)) == str(f.parent)
    assert core.local_scan_root("zip", str(tmp_path / "a.zip")) is None
    assert core.local_scan_root("git", "https://github.com/u/r") is None
    assert core.resolve_local_file(str(tmp_path), "skills/a/SKILL.md") == os.path.realpath(str(f))
    assert core.resolve_local_file(str(tmp_path), "skills/missing.md") is None
    assert core.resolve_local_file(str(tmp_path), "../outside.txt") is None
    assert core.resolve_local_file(None, "x") is None
    assert core.resolve_local_file(str(tmp_path), "") is None


def test_skills_subfolder(tmp_path):
    assert core.skills_subfolder(str(tmp_path)) is None
    (tmp_path / "skills").mkdir()
    assert core.skills_subfolder(str(tmp_path)) == str(tmp_path / "skills")
    assert core.skills_subfolder("") is None
    assert core.skills_subfolder(str(tmp_path / "nope")) is None


# ---------------------------------------------------------------- export, targets, scan

def test_markdown_export():
    r = load("report_ponytail.json")
    f = core.parse_findings(r)
    md = core.to_markdown("my-skill", f, core.count_by_severity(f), r)
    assert "DO_NOT_INSTALL" in md and "my-skill" in md and "Partial scan, coverage 81.9%" in md
    assert "## Hooks and plugin manifests" in md


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


def _fake_scan(monkeypatch, payload: bytes, code):
    def fake_run_stream(cmd, on_line, holder, extra_env=None, stdout_path=None):
        on_line("some stderr line")
        with open(stdout_path, "wb") as fh:
            fh.write(payload)
        return code
    monkeypatch.setattr(core, "run_stream", fake_run_stream)
    return core.run_scan("skillspector", "x", True, "openai", "", lambda l: None, {})


def test_report_with_utf8_bom_and_unicode_is_read(monkeypatch):
    payload = b"\xef\xbb\xbf" + json.dumps({"issues": [{"pattern": "café", "severity": "LOW"}]},
                                            ensure_ascii=False).encode("utf-8")
    res = _fake_scan(monkeypatch, payload, 1)
    assert res["ok"] and core.parse_findings(res["report"])[0]["title"] == "café"


def test_bad_json_keeps_raw_output_exit_code_and_stderr_separate(monkeypatch):
    res = _fake_scan(monkeypatch, b"Traceback: boom, not json", 2)
    assert not res["ok"] and res["report"] is None
    assert "exit code 2" in res["error"]
    assert res["raw_text"] == "Traceback: boom, not json" and res["returncode"] == 2
    assert "some stderr line" in res["log"] and "boom" not in res["log"]  # stderr not mixed into stdout


skillspector = core.find_skillspector()


@pytest.mark.skipif(not skillspector, reason="skillspector not installed")
def test_real_quick_scan(tmp_path):
    (tmp_path / "SKILL.md").write_text("---\nname: t\ndescription: t\n---\nCount words.\n")
    res = core.run_scan(skillspector, str(tmp_path), True, "openai", "", lambda l: None, {})
    assert res["ok"], res
    assert core.parse_findings(res["report"]) == []
