"""Where a finding lives -> which group it belongs to.  EDIT THE TABLE BELOW.

How rules work (paths are compared lower-case with forward slashes):
  "skills/"        a folder with this name anywhere in the path (also "a/b/" for nested folders)
  "SKILL.md"       a file name (the last part of the path)
  "README*"        a file name with wildcards (* and ?)

Groups are checked top to bottom and the FIRST match wins, so put the most
important groups first. A path that matches nothing goes to OTHER.
"""
import fnmatch

# (group name, short name used in sentences, collapsed at first?, rules)
GROUPS = [
    ("Skill files", "skill files", False,
     ["skills/", "SKILL.md"]),
    ("Hooks and plugin manifests", "hooks and plugin files", False,
     ["hooks/", ".claude-plugin/", ".opencode/", ".cursor-plugin/", "plugin.json", "marketplace.json"]),
    ("Install and scripts", "install files and scripts", False,
     ["INSTALL.md", "scripts/", ".github/workflows/"]),
    ("Tests, benchmarks, docs and examples", "tests, benchmarks and docs", True,
     ["tests/", "benchmarks/", "docs/", "examples/", "i18n/", "README*"]),
]
OTHER = ("Other", "other files", False, [])

ALL_GROUPS = GROUPS + [OTHER]


def _norm(path):
    p = str(path or "").replace("\\", "/").strip().lower()
    while p.startswith("./"):
        p = p[2:]
    return p.lstrip("/")


def _matches(rule, path):
    rule = rule.lower()
    if rule.endswith("/"):
        return ("/" + rule) in ("/" + path)
    return fnmatch.fnmatch(path.rsplit("/", 1)[-1], rule)


def group_for(path):
    """Return the group name for a file path ('' or None -> Other)."""
    p = _norm(path)
    if p:
        for name, _short, _collapsed, rules in GROUPS:
            if any(_matches(r, p) for r in rules):
                return name
    return OTHER[0]


def short_name(group):
    return next((g[1] for g in ALL_GROUPS if g[0] == group), group.lower())


def collapsed_by_default(group):
    return next((g[2] for g in ALL_GROUPS if g[0] == group), False)
