$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$api = Join-Path $repoRoot "engine\api"
$editor = Join-Path $repoRoot "engine\editor"

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
  throw "Python was not found. Install Python first; uv will fetch Python 3.11."
}

try { python -m uv --version | Out-Null } catch {
  python -m pip install --user uv
}

Push-Location $api
try { python -m uv sync --python 3.11 --frozen } finally { Pop-Location }

if (-not (Test-Path (Join-Path $editor "node_modules"))) {
  Push-Location $editor
  try { npm ci } finally { Pop-Location }
}

node (Join-Path $repoRoot "engine\export\sync-runtime.cjs")
Write-Host "Local generation engine is ready. Run pnpm dev."
