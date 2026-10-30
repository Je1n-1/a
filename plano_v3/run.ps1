$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (-not (Test-Path 'config.local.json')) {
    throw 'Execute .\setup.ps1 primeiro. O banco V3 precisa ser escolhido e inicializado explicitamente.'
}
$config = Get-Content config.local.json -Raw | ConvertFrom-Json
$planoPython = if ($config.python_path) { $config.python_path } else { Join-Path $PSScriptRoot '.venv\Scripts\python.exe' }
if (-not (Test-Path -LiteralPath $planoPython)) { throw 'Python configurado não encontrado. Confira python_path em config.local.json.' }
Write-Host "Plano V3: http://127.0.0.1:$($config.port)"
Write-Host "Banco: $($config.database_path)"
& $planoPython app.py --database $config.database_path --port $config.port
if ($LASTEXITCODE -ne 0) { throw 'O Plano não iniciou. Confira a mensagem acima.' }
