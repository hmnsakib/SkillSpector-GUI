# SkillSpector Scanner (Python / Tkinter, Windows first)

Simple GUI for NVIDIA's SkillSpector (security scanner for AI agent skills) for people who avoid cmd/PowerShell.
Open-source project (GitHub). Unofficial community wrapper, not affiliated with NVIDIA.

## Files
- `ss_core.py`  - all logic, NO GUI imports (detect git/uv/skillspector, install, scan, parse report, verdict, markdown export)
- `skillspector_gui.py` - Tkinter window (screens: checking, missing, installing, choose, scanning, results)
- `build.bat` - builds `dist\SkillSpectorScanner.exe` with PyInstaller (finds `py` or `python`)
- Design prototype (reference only): https://claude.ai/artifact/7Mkmos3HhVSxyvCWz5FyYc

## Rules
- Run programs with argument lists, never shell strings. Validate targets. API key only via the child's env, never saved/logged.
- Keep UI and logic separate; add unit tests for `ss_core.py` (pytest) using fixtures in `tests/fixtures/`.
- Resolve uv/git/skillspector by full path (PATH of the running app goes stale after installs).
- Scan command: `skillspector scan <target> --format json [--no-llm]`. Do NOT pass `--output`: the real tool
  exits 2 ("Safe file output is unsupported on this platform"). JSON is read from stdout, redirected to a temp file.

## Known unknowns (verify first)
1. Real JSON schema of `skillspector scan --format json` -> save one real report as a fixture, make `parse_findings` exact.
2. Exit codes / full `scan --help` options.
3. Behaviour without API key and without `--no-llm`.
4. The GUI has only been run by the user, never by Claude in a test; expect rough edges (layout, DPI, fonts).

## Next tasks
1. Run on real Windows, fix any GUI bugs, make the parser match the real report.
2. Build scripts `build_macos.sh`, `build_linux.sh` (run on each OS; PyInstaller cannot cross-compile).
   macOS needs a different button style (tk.Button colours are ignored on macOS). Apple Silicon vs Intel are separate builds.
3. GitHub Actions workflow (windows/macos/ubuntu runners) that builds and attaches files to a GitHub Release with fixed names:
   `SkillSpectorScanner-windows.exe`, `-macos.zip`, `-linux.tar.gz`.
4. README with one-click download links (`releases/latest/download/<name>`), screenshots, LICENSE (Apache-2.0), unofficial notice.
   Never commit built binaries to the repo.
5. Possible later rewrite in Flutter (separate hand-off kit exists).
