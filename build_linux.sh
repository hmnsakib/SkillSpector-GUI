#!/usr/bin/env bash
# Builds dist/SkillSpectorScanner-linux.tar.gz (run on Linux; PyInstaller cannot cross-compile).
set -euo pipefail
cd "$(dirname "$0")"
PY="${PYTHON:-python3}"
"$PY" -c "import tkinter" 2>/dev/null || { echo "Python has no Tkinter. Install it first, e.g.: sudo apt install python3-tk"; exit 1; }
"$PY" -m pip install --upgrade pyinstaller
"$PY" -m PyInstaller --noconfirm --clean --windowed --onefile --name SkillSpectorScanner skillspector_gui.py
cd dist
rm -f SkillSpectorScanner-linux.tar.gz
tar -czf SkillSpectorScanner-linux.tar.gz SkillSpectorScanner
echo "Done: dist/SkillSpectorScanner-linux.tar.gz"
