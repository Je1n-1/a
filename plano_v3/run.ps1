$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (-not (Test-Path '.venv\Scripts\python.exe') -or -not (Test-Path 'config.local.json')) {
    throw 'Execute .\setup.ps1 primeiro. O banco V3 precisa ser escolhido e inicializado explicitamente.'
}
$config = Get-Content config.local.json -Raw | ConvertFrom-Json
Write-Host "Plano V3: http://127.0.0.1:$($config.port)"
Write-Host "Banco: $($config.database_path)"
& .\.venv\Scripts\python.exe app.py --database $config.database_path --port $config.port
if ($LASTEXITCODE -ne 0) { throw 'O Plano não iniciou. Confira a mensagem acima.' }
