# SkillSpector Scanner

A simple desktop window for [NVIDIA SkillSpector](https://github.com/NVIDIA/skillspector), the security scanner for AI agent skills.
For people who would rather not use a terminal: pick a skill, click **Scan**, read a plain-language verdict.

> **Unofficial.** This is a community wrapper and is not affiliated with or endorsed by NVIDIA.
> A clean result is not proof that a skill is safe.

## Download

| System | Download |
|---|---|
| Windows | [SkillSpectorScanner-windows.exe](../../releases/latest/download/SkillSpectorScanner-windows.exe) |
| macOS (this build matches the CPU it was built on) | [SkillSpectorScanner-macos.zip](../../releases/latest/download/SkillSpectorScanner-macos.zip) |
| Linux | [SkillSpectorScanner-linux.tar.gz](../../releases/latest/download/SkillSpectorScanner-linux.tar.gz) |

The app is unsigned: Windows SmartScreen may warn ("More info" > "Run anyway"); on macOS right-click the app > Open.
On first start it installs `uv` and SkillSpector for your account (and Git via winget on Windows if missing).

<!-- screenshots: add images to docs/ and link them here -->

## What it does

- Scan a skill **folder**, a `SKILL.md` file, a **zip**, or a **GitHub link**
- **Quick scan** (built-in static checks, no account) or AI review with your own API key (used for that scan only, never saved)
- Findings sorted by severity, with explanations and how to fix; export as Markdown or JSON

Under the hood: `skillspector scan <target> --format json [--no-llm]`.

## Run from source

Requires Python 3.12+ with Tkinter.

```
python skillspector_gui.py
python -m pip install pytest && python -m pytest tests
```

## Build

`build.bat` (Windows), `./build_macos.sh`, `./build_linux.sh`. PyInstaller cannot cross-compile, so run each on its own OS.
Pushing a tag like `v0.1.0` makes GitHub Actions build all three and attach them to a Release.
Built binaries are never committed.

## License

Apache-2.0, see [LICENSE](LICENSE). SkillSpector itself is a separate project with its own license.
