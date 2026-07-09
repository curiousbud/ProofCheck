# `scripts/` — setup automation

Cross-platform setup for ProofCheck. Each script installs the **Tesseract OCR engine**
(for the optional, deterministic OCR fallback), creates a Python virtualenv, installs the
package with its `dev` + `ocr` extras, and runs the test-suite. All steps are idempotent —
safe to re-run.

| OS | Command |
|----|---------|
| Linux / macOS | `bash scripts/setup.sh` |
| Windows (PowerShell) | `powershell -ExecutionPolicy Bypass -File scripts\setup.ps1` |

## Options

**`setup.sh`** (environment variables):
- `PYTHON=python3.12` — choose the interpreter (default `python3`).
- `VENV_DIR=.venv` — virtualenv location.
- `SKIP_TESSERACT=1` — skip the engine install (e.g. it's managed elsewhere).

**`setup.ps1`** (parameters):
- `-Python py` — choose the interpreter (default `python`).
- `-VenvDir .venv` — virtualenv location.
- `-SkipTesseract` — skip the engine install.

## What gets installed

- **Tesseract OCR engine** via the platform package manager (the scripts try each in
  order and stop at the first one present):
  - Linux: `apt-get` / `dnf` / `yum` / `pacman` / `zypper` / `apk` / `xbps-install` (Void) /
    `eopkg` (Solus) / `nix-env`
  - macOS: Homebrew (`brew`) → MacPorts (`port`)
  - Windows: `winget` (UB-Mannheim build) → `choco` → `scoop` → direct UB-Mannheim installer
    download (silent) as a last resort
- **Python deps**: `pip install -e ".[dev,ocr]"` (core + tests + OCR helpers
  `pytesseract` / `Pillow` / `pypdfium2`).

The Tesseract **binary** is the one piece pip can't provide. If auto-install isn't
possible (no package manager / no privileges), the script prints a manual-install pointer
and continues — ProofCheck still works, just with OCR disabled until the engine is present
(`proofcheck.ocr.available()` reports the status).

> Tip: set `TESSERACT_CMD=/full/path/to/tesseract` to point ProofCheck at a non-standard
> install location. On Windows it also auto-discovers `C:\Program Files\Tesseract-OCR`.
