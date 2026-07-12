<#
.SYNOPSIS
    ProofCheck setup - Windows (PowerShell 5.1+).

.DESCRIPTION
    Installs the Tesseract OCR engine (for the optional, deterministic OCR fallback),
    creates a Python virtualenv, and installs ProofCheck with its dev + ocr extras.
    Re-runnable: every step is a no-op when already satisfied.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\setup.ps1

.EXAMPLE
    # Skip the engine install, or pick a specific interpreter:
    powershell -ExecutionPolicy Bypass -File scripts\setup.ps1 -SkipTesseract -Python py
#>
[CmdletBinding()]
param(
    [string]$Python = "python",
    [string]$VenvDir = ".venv",
    [switch]$SkipTesseract
)

$ErrorActionPreference = "Stop"
function Info($m) { Write-Host "[setup] $m" -ForegroundColor Cyan }
function Warn($m) { Write-Host "[setup] $m" -ForegroundColor Yellow }

# Run from the repo root (this script lives in <root>\scripts).
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$TessDir = "C:\Program Files\Tesseract-OCR"

# Last-resort fallback: download the UB-Mannheim installer and run it silently (NSIS /S).
# Returns $true on success. Used only when no package manager (winget/choco/scoop) is present.
function Install-TesseractFromInstaller {
    $url = "https://digi.bib.uni-mannheim.de/tesseract/tesseract-ocr-w64-setup-5.5.0.20241111.exe"
    $exe = Join-Path $env:TEMP "tesseract-ocr-setup.exe"
    try {
        Info "Downloading the Tesseract installer from UB-Mannheim..."
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

        if ($PSVersionTable.PSVersion.Major -lt 6) {
            Invoke-WebRequest -Uri $url -OutFile $exe -UseBasicParsing
        } else {
            Invoke-WebRequest -Uri $url -OutFile $exe
        }

        $sig = Get-AuthenticodeSignature -FilePath $exe
        if ($sig.Status -ne 'Valid') {
            throw "Downloaded installer signature check failed: $($sig.Status)"
        }

        Info "Running the installer silently (this may take a minute)..."
        $p = Start-Process -FilePath $exe -ArgumentList "/S" -Wait -PassThru
        if ($p.ExitCode -ne 0) {
            throw "Installer exited with code $($p.ExitCode)"
        }

        return (Test-Path "$TessDir\tesseract.exe")
    } catch {
        Warn "Installer download/run failed: $($_.Exception.Message)"
        return $false
    } finally {
        Remove-Item $exe -ErrorAction SilentlyContinue
    }
}

function Install-Tesseract {
    if ($SkipTesseract) { Warn "-SkipTesseract set - skipping engine install."; return }
    if (Get-Command tesseract -ErrorAction SilentlyContinue) { Info "Tesseract already on PATH."; return }
    if (Test-Path "$TessDir\tesseract.exe") { Info "Tesseract already installed in Program Files."; return }

    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Info "Installing Tesseract via winget (UB-Mannheim build)..."
        winget install --id UB-Mannheim.TesseractOCR -e --accept-source-agreements --accept-package-agreements --silent
    } elseif (Get-Command choco -ErrorAction SilentlyContinue) {
        Info "Installing Tesseract via Chocolatey..."
        choco install tesseract -y
    } elseif (Get-Command scoop -ErrorAction SilentlyContinue) {
        Info "Installing Tesseract via Scoop..."
        scoop install tesseract
    } elseif (Install-TesseractFromInstaller) {
        Info "Installed Tesseract from the UB-Mannheim installer."
    } else {
        Warn "No winget/choco/scoop found and the direct download failed. Install Tesseract manually"
        Warn "  from https://github.com/UB-Mannheim/tesseract/wiki  (OCR stays disabled until then)."
        return
    }

    # Make it usable in THIS session even though the installer's PATH update won't apply yet.
    if ((Test-Path "$TessDir\tesseract.exe") -and ($env:PATH -notlike "*$TessDir*")) {
        $env:PATH = "$TessDir;$env:PATH"
    }
}

Info "Using Python: $(& $Python --version 2>&1)"

Install-Tesseract

if (-not (Test-Path $VenvDir)) {
    Info "Creating virtualenv at $VenvDir"
    & $Python -m venv $VenvDir
} else {
    Info "Reusing existing virtualenv at $VenvDir"
}

$Py = Join-Path $VenvDir "Scripts\python.exe"
Info "Upgrading pip and installing ProofCheck (dev + ocr extras)"
& $Py -m pip install --upgrade pip
& $Py -m pip install -e ".[dev,ocr]"

Info "Running the test suite"
& $Py -m pytest -q

# proofcheck.ocr auto-discovers the engine in Program Files, so this reports True even if
# PATH hasn't refreshed in this session. Double-quote the PS argument and single-quote the
# Python inside it, so PowerShell passes the quotes through to python.exe intact.
& $Py -c "import proofcheck.ocr as o; print('[setup] OCR available:', o.available(), '-', o.unavailable_reason() or 'ready')"

Info "Done. Activate the environment with:  .\$VenvDir\Scripts\Activate.ps1"
