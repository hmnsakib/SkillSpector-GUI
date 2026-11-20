#!/usr/bin/env bash
# Builds dist/SkillSpectorScanner-macos.zip (run on a Mac; builds for THIS Mac's CPU: Apple Silicon or Intel).
set -euo pipefail
cd "$(dirname "$0")"
PY="${PYTHON:-python3}"
"$PY" -c "import tkinter" 2>/dev/null || { echo "Python has no Tkinter. Install Python from python.org (includes Tk) or: brew install python-tk"; exit 1; }
"$PY" -m pip install --upgrade pyinstaller
"$PY" -m PyInstaller --noconfirm --clean --windowed --name SkillSpectorScanner skillspector_gui.py
cd dist
rm -f SkillSpectorScanner-macos.zip
ditto -c -k --sequesterRsrc --keepParent SkillSpectorScanner.app SkillSpectorScanner-macos.zip
echo "Done: dist/SkillSpectorScanner-macos.zip  ($(uname -m))"
echo "Note: the app is unsigned. Users right-click > Open the first time."
