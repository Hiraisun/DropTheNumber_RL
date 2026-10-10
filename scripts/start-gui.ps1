param([switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$guiUrl = 'http://127.0.0.1:8765/'
$response = $null
try { $response = Invoke-WebRequest -UseBasicParsing -Uri $guiUrl -TimeoutSec 2 } catch { }
if ($response) {
    if ($response.Content -notmatch 'dtn-token|id="setup"') { throw 'Port 8765 is already used by another application.' }
    if (-not $NoBrowser) { Start-Process $guiUrl }
    exit
}
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if (-not $pythonCommand) { throw 'Install Python 3.12 or later before starting the GUI.' }
    $pythonPath = $pythonCommand.Source
}
$env:PYTHONPATH = Join-Path $projectRoot 'src'
$logDirectory = Join-Path $projectRoot 'artifacts\gui'
New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
$errorLog = Join-Path $logDirectory 'server-error.log'
$outputLog = Join-Path $logDirectory 'server-output.log'
$guiProcess = Start-Process -FilePath $pythonPath -ArgumentList '-m drop_the_number.dashboard.server --no-browser' -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardError $errorLog -RedirectStandardOutput $outputLog
for ($attempt = 0; $attempt -lt 40; $attempt++) {
    Start-Sleep -Milliseconds 250
    if ($guiProcess.HasExited) { throw "GUI startup failed. Read: $errorLog" }
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $guiUrl -TimeoutSec 1
        if ($response.Content -match 'dtn-token|id="setup"') {
            if (-not $NoBrowser) { Start-Process $guiUrl }
            exit
        }
    } catch { }
}
throw "GUI startup timed out. Read: $errorLog"
