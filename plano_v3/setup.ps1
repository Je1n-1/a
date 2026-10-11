param(
    [string]$DatabasePath = (Join-Path $env:LOCALAPPDATA 'PlanoV3\data\plano.db'),
    [string]$PythonExecutable,
    [int]$Port = 5054
)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (-not (Test-Path '.venv\Scripts\python.exe')) {
    if (-not $PythonExecutable) {
        $pythonCommand = Get-Command py -ErrorAction SilentlyContinue
        if ($null -eq $pythonCommand) { $pythonCommand = Get-Command python -ErrorAction Stop }
        $PythonExecutable = $pythonCommand.Source
    }
    & $PythonExecutable -c "import sys; sys.exit(0 if sys.version_info >= (3,12) else 1)"
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 ou superior não encontrado. Instale-o ou informe -PythonExecutable com o caminho do python.exe.' }
    & $PythonExecutable -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Não foi possível criar o ambiente Python.' }
}
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Não foi possível instalar as dependências.' }
& .\.venv\Scripts\python.exe app.py --database $DatabasePath --init-db
if ($LASTEXITCODE -ne 0) { throw 'Inicialização interrompida. Confira o banco informado.' }
# Resolve também redirecionamentos do Windows; o mesmo caminho será usado no run.ps1.
$resolvedDatabase = & .\.venv\Scripts\python.exe -c "import pathlib,sys; print(pathlib.Path(sys.argv[1]).resolve())" $DatabasePath
@{ database_path = $resolvedDatabase; port = $Port } | ConvertTo-Json | Set-Content -Encoding utf8 config.local.json
Write-Host "Banco V3: $resolvedDatabase"
Write-Host "Pronto. Execute .\run.ps1 e abra http://127.0.0.1:$Port"
