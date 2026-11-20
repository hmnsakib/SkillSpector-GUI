"""Core logic for SkillSpector Scanner: detection, install, scan, report parsing.

No GUI imports here, so this can be tested on its own.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

REPO = "git+https://github.com/NVIDIA/skillspector.git"
UV_WIN_INSTALL = "irm https://astral.sh/uv/install.ps1 | iex"
UV_UNIX_INSTALL = "curl -LsSf https://astral.sh/uv/install.sh | sh"
GIT_DOWNLOAD_URL = "https://git-scm.com/downloads"

IS_WIN = os.name == "nt"
CREATE_NO_WINDOW = 0x08000000 if IS_WIN else 0
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


# ---------------------------------------------------------------- environment

def extra_dirs():
    """Folders where uv / skillspector / git usually live but PATH may not know yet."""
    home = os.path.expanduser("~")
    dirs = [os.path.join(home, ".local", "bin"), os.path.join(home, ".cargo", "bin")]
    if IS_WIN:
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")
        local = os.environ.get("LOCALAPPDATA", "")
        dirs += [
            os.path.join(pf, "Git", "cmd"),
            os.path.join(local, "Programs", "Git", "cmd"),
        ]
    return [d for d in dirs if d and os.path.isdir(d)]


def build_env(extra=None):
    env = os.environ.copy()
    env["PATH"] = os.pathsep.join(extra_dirs() + [env.get("PATH", "")])
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["NO_COLOR"] = "1"
    if extra:
        env.update(extra)
    return env


def find_exe(name):
    return shutil.which(name, path=build_env()["PATH"])


def _run_quiet(cmd, timeout=20):
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, env=build_env(), stdin=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW,
        )
        return r.returncode, (r.stdout or "").strip()
    except (OSError, subprocess.SubprocessError):
        return -1, ""


def find_skillspector(uv=None):
    exe = find_exe("skillspector")
    if exe:
        return exe
    uv = uv or find_exe("uv")
    if uv:
        code, out = _run_quiet([uv, "tool", "dir", "--bin"])
        if code == 0 and out:
            cand = os.path.join(out.splitlines()[-1].strip(),
                                "skillspector.exe" if IS_WIN else "skillspector")
            if os.path.isfile(cand):
                return cand
    return None


def check_status():
    uv = find_exe("uv")
    return {"git": find_exe("git"), "uv": uv, "skillspector": find_skillspector(uv)}


# ---------------------------------------------------------------- running commands

def strip_ansi(s):
    return ANSI_RE.sub("", s)


def kill_tree(proc):
    if proc is None or proc.poll() is not None:
        return
    try:
        if IS_WIN:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True, creationflags=CREATE_NO_WINDOW)
        else:
            proc.terminate()
    except OSError:
        pass


def run_stream(cmd, on_line, holder, extra_env=None, stdout_path=None):
    """Run cmd (list, never a shell string), stream output line by line.

    Normally stdout and stderr are merged into the live log. If stdout_path is
    given, stdout is written to that file (used for reports) and only stderr is
    streamed to the log.
    holder is a dict; holder['proc'] is set so another thread can cancel.
    Returns the exit code, or -1 if the program could not be started.
    """
    out_fh = None
    try:
        if stdout_path:
            out_fh = open(stdout_path, "wb")
            stdout_arg, stderr_arg = out_fh, subprocess.PIPE
        else:
            stdout_arg, stderr_arg = subprocess.PIPE, subprocess.STDOUT
        proc = subprocess.Popen(
            cmd, stdout=stdout_arg, stderr=stderr_arg,
            stdin=subprocess.DEVNULL, text=False,
            env=build_env(extra_env), creationflags=CREATE_NO_WINDOW,
        )
    except OSError as e:
        if out_fh:
            out_fh.close()
        on_line("Could not start: %s" % e)
        return -1
    holder["proc"] = proc
    try:
        stream = proc.stderr if stdout_path else proc.stdout
        for raw in stream:
            line = strip_ansi(raw.decode("utf-8", errors="replace").rstrip("\r\n"))
            if line.strip():
                on_line(line)
        return proc.wait()
    finally:
        if out_fh:
            out_fh.close()


# ---------------------------------------------------------------- install

def install_plan(status):
    """Return the list of step labels the install will go through."""
    steps = []
    if not status.get("git"):
        steps.append("Installing Git")
    if not status.get("uv"):
        steps.append("Installing uv")
    steps.append("Installing SkillSpector (downloads Python 3.12 if needed)")
    return steps


def install_all(status, on_step, on_line, holder):
    """Install whatever is missing. Calls on_step(i) as each step starts.

    Returns (ok, message).
    """
    i = 0
    if not status.get("git"):
        on_step(i); i += 1
        winget = shutil.which("winget")
        if IS_WIN and winget:
            code = run_stream([winget, "install", "--id", "Git.Git", "-e", "--source", "winget",
                               "--accept-package-agreements", "--accept-source-agreements"],
                              on_line, holder)
            if code != 0 and not find_exe("git"):
                return False, "Git could not be installed automatically. Install it from %s and reopen this app." % GIT_DOWNLOAD_URL
        if not find_exe("git"):
            return False, "Git is required. Install it from %s, then reopen this app." % GIT_DOWNLOAD_URL
        if holder.get("cancelled"):
            return False, "Cancelled."

    uv = find_exe("uv")
    if not uv:
        on_step(i); i += 1
        if IS_WIN:
            cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", UV_WIN_INSTALL]
        else:
            cmd = ["sh", "-c", UV_UNIX_INSTALL]
        code = run_stream(cmd, on_line, holder)
        uv = find_exe("uv")
        if code != 0 or not uv:
            return False, "uv could not be installed. Check your internet connection and try again."
        if holder.get("cancelled"):
            return False, "Cancelled."

    on_step(i)
    code = run_stream([uv, "tool", "install", "--python", "3.12", REPO], on_line, holder)
    if holder.get("cancelled"):
        return False, "Cancelled."
    if code != 0:
        return False, "SkillSpector could not be installed (see details)."
    if not find_skillspector(uv):
        return False, "Install finished but SkillSpector was not found. Try reopening the app."
    return True, "Installed."


# ---------------------------------------------------------------- scan

def validate_target(kind, target):
    """Return an error string, or None if the target looks acceptable."""
    t = (target or "").strip()
    if not t:
        return "Choose or paste something to scan first."
    if t.startswith("-"):
        return "That doesn't look like a valid path or link."
    if kind == "git":
        if not re.match(r"^(https?://|git@)\S+$", t):
            return "Paste a full link, for example https://github.com/user/my-skill"
    else:
        if not os.path.exists(t):
            return "That path doesn't exist."
        if kind == "folder" and not os.path.isdir(t):
            return "That is not a folder."
        if kind in ("file", "zip") and not os.path.isfile(t):
            return "That is not a file."
    return None


def _load_json_text(text):
    """Parse JSON, tolerating stray text before/after it. Returns object or None."""
    text = (text or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except ValueError:
        pass
    a, b = text.find("{"), text.rfind("}")
    if a != -1 and b > a:
        try:
            return json.loads(text[a:b + 1])
        except ValueError:
            pass
    return None


def run_scan(skillspector, target, quick, api_provider, api_key, on_line, holder):
    """Run a scan. Returns dict: ok, error, report (parsed JSON or None), raw_text, returncode.

    SkillSpector on some platforms refuses --output ("Safe file output is unsupported"),
    so the JSON report is read from stdout, which we redirect to a new file in a
    private temp folder (outside the scan target).
    """
    tmpdir = tempfile.mkdtemp(prefix="skillspector_")
    out_path = os.path.join(tmpdir, "report.json")
    cmd = [skillspector, "scan", target, "--format", "json"]
    extra = None
    if quick:
        cmd.append("--no-llm")
    elif api_key:
        extra = {"SKILLSPECTOR_PROVIDER": (api_provider or "openai").lower(),
                 "OPENAI_API_KEY": api_key}
    lines = []

    def collect(line):
        lines.append(line)
        on_line(line)

    try:
        code = run_stream(cmd, collect, holder, extra, stdout_path=out_path)
        result = {"returncode": code, "log": "\n".join(lines), "report": None, "raw_text": "",
                  "ok": False, "error": None}
        if holder.get("cancelled"):
            result["error"] = "Cancelled."
            return result
        if os.path.isfile(out_path):
            with open(out_path, "r", encoding="utf-8", errors="replace") as f:
                result["raw_text"] = f.read()
            result["report"] = _load_json_text(result["raw_text"])
            result["ok"] = result["report"] is not None
        if not result["ok"]:
            if "No LLM API key" in result["log"]:
                result["error"] = ("AI review needs an API key. Enter one, or turn Quick scan back on.")
            else:
                # exit 1 = risk found (report still produced); exit 2 = real error, no report
                result["error"] = ("The scan did not produce a readable report (exit code %s). "
                                   "See details below." % code)
        return result
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------- report parsing

LIST_KEYS = ("findings", "issues", "vulnerabilities", "results", "detections", "alerts")
TITLE_KEYS = ("title", "name", "rule_name", "rule", "pattern", "category", "id", "type")
DESC_KEYS = ("description", "message", "details", "explanation", "summary", "reason")
SEV_KEYS = ("severity", "level", "risk", "priority")
FILE_KEYS = ("file", "path", "file_path", "filename")


def _pick(d, keys):
    for k in keys:
        v = d.get(k)
        if v not in (None, "", [], {}):
            return v
    return None


def norm_severity(v):
    s = str(v or "").strip().lower()
    if s in ("critical", "high", "severe", "error"):
        return "High"
    if s in ("medium", "moderate", "warning", "warn"):
        return "Medium"
    return "Low"


def _location(d):
    f = _pick(d, FILE_KEYS)
    loc = d.get("location")
    line = d.get("line") or d.get("line_number") or d.get("lineno")
    if isinstance(loc, dict):
        f = f or _pick(loc, FILE_KEYS)
        line = line or loc.get("line") or loc.get("start_line")
    elif isinstance(loc, str) and not f:
        f = loc
    if f and line:
        return "%s · line %s" % (f, line)
    return str(f) if f else ""


def _find_list(obj, depth=0):
    if isinstance(obj, list) and obj and all(isinstance(x, dict) for x in obj):
        return obj
    if isinstance(obj, dict) and depth < 3:
        for k in LIST_KEYS:
            if k in obj:
                r = _find_list(obj[k], depth + 1)
                if r is not None:
                    return r
                if obj[k] == []:
                    return []
        for v in obj.values():
            if isinstance(v, (dict, list)):
                r = _find_list(v, depth + 1)
                if r is not None:
                    return r
    return None


def _issue_location(issue):
    loc = issue.get("location")
    if not isinstance(loc, dict) or not loc.get("file"):
        return ""
    return "%s · line %s" % (loc["file"], loc["start_line"]) if loc.get("start_line") else str(loc["file"])


def _parse_real_issues(report):
    """Exact parser for SkillSpector 2.x: top-level 'issues' list."""
    out = []
    for it in report["issues"]:
        if not isinstance(it, dict):
            continue
        desc = str(it.get("explanation") or "")
        if it.get("remediation"):
            desc += ("\n\n" if desc else "") + "How to fix: " + str(it["remediation"])
        title = str(it.get("pattern") or it.get("category") or "Finding")
        if it.get("category") and it.get("pattern"):
            title = "%s: %s" % (it["category"], it["pattern"])
        out.append({
            "severity": norm_severity(it.get("severity")),
            "title": title,
            "description": desc,
            "where": _issue_location(it),
        })
    return out


def risk_summary(report):
    """Return (recommendation, score) from risk_assessment, or (None, None)."""
    ra = report.get("risk_assessment") if isinstance(report, dict) else None
    if not isinstance(ra, dict):
        return None, None
    return ra.get("recommendation"), ra.get("score")


def incomplete_note(report):
    """Return a warning string if the scan only partly covered the skill, else ''."""
    ac = report.get("analysis_completeness") if isinstance(report, dict) else None
    if isinstance(ac, dict) and ac.get("is_complete") is False:
        return "Coverage was %s%%: some files or checks were not fully inspected." % ac.get("coverage_percent", "?")
    return ""


def parse_findings(report):
    """Return a list of finding dicts, or None if the report format wasn't recognised."""
    out = None
    if isinstance(report, dict) and isinstance(report.get("issues"), list):
        out = _parse_real_issues(report)
        order = {"High": 0, "Medium": 1, "Low": 2}
        out.sort(key=lambda f: order[f["severity"]])
        return out
    items = _find_list(report)
    if items is None:
        return None
    out = []
    for it in items:
        out.append({
            "severity": norm_severity(_pick(it, SEV_KEYS)),
            "title": str(_pick(it, TITLE_KEYS) or "Finding"),
            "description": str(_pick(it, DESC_KEYS) or ""),
            "where": _location(it),
        })
    order = {"High": 0, "Medium": 1, "Low": 2}
    out.sort(key=lambda f: order[f["severity"]])
    return out


def count_by_severity(findings):
    c = {"High": 0, "Medium": 0, "Low": 0}
    for f in findings:
        c[f["severity"]] += 1
    return c


RECOMMENDATIONS = {
    "DO_NOT_INSTALL": ("Do not install", "SkillSpector rates this skill as dangerous. Review the findings below.", "bad"),
    "CAUTION": ("Review before installing", "Some risky patterns were found. Read them below.", "warn"),
    "SAFE": ("No serious issues found", "A clean result is not proof the skill is safe.", "ok"),
}


def verdict(counts, recommendation=None):
    """(label, explanation, level) where level is 'bad' | 'warn' | 'ok'.

    If SkillSpector's own recommendation is known it wins over our counting.
    """
    if recommendation in RECOMMENDATIONS:
        return RECOMMENDATIONS[recommendation]
    if counts["High"]:
        n = counts["High"]
        return ("Do not install",
                "%d serious problem%s found. Review them below." % (n, "" if n == 1 else "s"), "bad")
    if counts["Medium"]:
        return ("Review before installing", "Some risky patterns were found. Read them below.", "warn")
    if counts["Low"]:
        return ("Minor issues only", "Only low-risk items were found.", "ok")
    return ("No issues found", "A clean result is not proof the skill is safe.", "ok")


def to_markdown(target, findings, counts, recommendation=None):
    lab, expl, _ = verdict(counts, recommendation)
    lines = ["# SkillSpector report", "", "Scanned: %s" % target, "",
             "**%s** - %s" % (lab, expl), "",
             "High: %d | Medium: %d | Low: %d" % (counts["High"], counts["Medium"], counts["Low"]), ""]
    for f in findings:
        lines.append("## [%s] %s" % (f["severity"], f["title"]))
        if f["description"]:
            lines.append(f["description"])
        if f["where"]:
            lines.append("`%s`" % f["where"])
        lines.append("")
    lines.append("_A clean result is not proof a skill is safe._")
    return "\n".join(lines)
