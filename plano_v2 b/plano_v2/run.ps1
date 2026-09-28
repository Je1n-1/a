$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$localPython = Join-Path $root '.venv\Scripts\python.exe'
$sharedPython = Join-Path (Split-Path -Parent $root) '.venv\Scripts\python.exe'

if (Test-Path $localPython) {
    $python = $localPython
} elseif (Test-Path $sharedPython) {
    $python = $sharedPython
} else {
    throw 'Ambiente não encontrado. Execute .\setup.ps1, ou ative o ambiente em ..\.venv.'
}

# A porta exclusiva evita abrir a aplicação legada que pode estar usando 5000.
$env:PLANO_PORT = '5051'
Write-Host 'Plano V2 disponível em http://127.0.0.1:5051'
& $python app.py
