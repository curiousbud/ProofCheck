#!/usr/bin/env bash
#
# ProofCheck setup — Linux / macOS.
#
# Installs the Tesseract OCR engine (for the optional, deterministic OCR fallback),
# creates a Python virtualenv, and installs ProofCheck with its dev + ocr extras.
# Re-runnable: every step is a no-op when already satisfied.
#
# Usage:
#   bash scripts/setup.sh                 # full setup
#   SKIP_TESSERACT=1 bash scripts/setup.sh   # skip the engine install
#   PYTHON=python3.12 bash scripts/setup.sh  # pick a specific interpreter
#
set -euo pipefail

PYTHON="${PYTHON:-python3}"
VENV_DIR="${VENV_DIR:-.venv}"
# Resolve repo root (this script lives in <root>/scripts).
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

info() { printf '\033[1;34m[setup]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[setup]\033[0m %s\n' "$*" >&2; }
err()  { printf '\033[1;31m[setup]\033[0m %s\n' "$*" >&2; }

install_tesseract() {
  if [ "${SKIP_TESSERACT:-0}" = "1" ]; then
    warn "SKIP_TESSERACT=1 set — skipping engine install."
    return
  fi
  if command -v tesseract >/dev/null 2>&1; then
    info "Tesseract already installed: $(tesseract --version 2>&1 | head -1)"
    return
  fi

  local os; os="$(uname -s)"
  info "Installing the Tesseract OCR engine for $os ..."
  case "$os" in
    Linux)
      if   command -v apt-get >/dev/null 2>&1; then sudo apt-get update && sudo apt-get install -y tesseract-ocr
      elif command -v dnf     >/dev/null 2>&1; then sudo dnf install -y tesseract
      elif command -v yum     >/dev/null 2>&1; then sudo yum install -y tesseract
      elif command -v pacman  >/dev/null 2>&1; then sudo pacman -Sy --noconfirm tesseract
      elif command -v zypper  >/dev/null 2>&1; then sudo zypper install -y tesseract-ocr
      elif command -v apk     >/dev/null 2>&1; then sudo apk add tesseract-ocr
      else warn "No known package manager found. Install 'tesseract-ocr' manually."
      fi
      ;;
    Darwin)
      if command -v brew >/dev/null 2>&1; then brew install tesseract
      else warn "Homebrew not found. Install it from https://brew.sh then run 'brew install tesseract'."
      fi
      ;;
    *)
      warn "Unsupported OS '$os' for auto-install. Install Tesseract manually; OCR will stay disabled until then."
      ;;
  esac
}

main() {
  command -v "$PYTHON" >/dev/null 2>&1 || { err "Python interpreter '$PYTHON' not found."; exit 1; }
  info "Using Python: $("$PYTHON" --version 2>&1)"

  install_tesseract

  if [ ! -d "$VENV_DIR" ]; then
    info "Creating virtualenv at $VENV_DIR"
    "$PYTHON" -m venv "$VENV_DIR"
  else
    info "Reusing existing virtualenv at $VENV_DIR"
  fi
  # shellcheck disable=SC1091
  source "$VENV_DIR/bin/activate"

  info "Upgrading pip and installing ProofCheck (dev + ocr extras)"
  python -m pip install --upgrade pip
  python -m pip install -e ".[dev,ocr]"

  info "Running the test suite"
  python -m pytest -q || warn "Some tests failed — see output above."

  python - <<'PY'
import proofcheck.ocr as ocr
print(f"[setup] OCR available: {ocr.available()}  ({ocr.unavailable_reason() or 'ready'})")
PY

  info "Done. Activate the environment with:  source $VENV_DIR/bin/activate"
}

main "$@"
