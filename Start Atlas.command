#!/bin/bash
# Double-click this file (macOS) to start Atlas in your web browser.
# Linux: run ./"Start Atlas.command" from a terminal.
#
# First run sets up a private Python environment in .venv/ (a minute or two);
# after that it starts in a few seconds.
set -euo pipefail
cd "$(dirname "$0")"

fail() {
  echo
  echo "  $1"
  echo
  read -r -p "  Press Return to close this window." _ || true
  exit 1
}

# Find a Python 3.10+ interpreter.
PYTHON=""
for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$candidate" >/dev/null 2>&1 &&
     "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
    PYTHON="$(command -v "$candidate")"
    break
  fi
done
[[ -n "$PYTHON" ]] || fail "Atlas needs Python 3.10 or newer. Install it from https://www.python.org/downloads/ and double-click this file again."

# Install (or re-install after an update changed pyproject.toml).
STAMP=".venv/.atlas-installed"
if [[ ! -x .venv/bin/python || ! -f "$STAMP" || pyproject.toml -nt "$STAMP" ]]; then
  echo "Setting up Atlas (first run only, takes a minute or two)..."
  [[ -x .venv/bin/python ]] || "$PYTHON" -m venv .venv || fail "Couldn't create the Python environment."
  .venv/bin/python -m pip install --quiet --upgrade pip || true
  .venv/bin/python -m pip install --quiet -e . || fail "Installing Atlas failed -- see the messages above."
  touch "$STAMP"
fi

if ! command -v claude >/dev/null 2>&1 && [[ ! -x "$HOME/.local/bin/claude" ]]; then
  echo
  echo "  Note: Claude Code isn't installed yet. Atlas will open, but it needs Claude Code"
  echo "  to read sources and answer questions: https://claude.com/claude-code"
  echo
fi

exec .venv/bin/atlas ui "$@"
