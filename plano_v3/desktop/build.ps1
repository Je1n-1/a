param([switch]$CreateShortcut)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$buildDir = Join-Path $PSScriptRoot 'build'
New-Item -ItemType Directory -Force -Path $buildDir | Out-Null
$compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path -LiteralPath $compiler)) { throw 'Compilador .NET Framework não encontrado.' }
Add-Type -AssemblyName System.Drawing
$bitmap = New-Object System.Drawing.Bitmap 64,64
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$graphics.Clear([System.Drawing.Color]::FromArgb(91,221,186))
$font = New-Object System.Drawing.Font 'Georgia',42,([System.Drawing.FontStyle]::Bold),([System.Drawing.GraphicsUnit]::Pixel)
$brush = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(16,27,37))
$graphics.DrawString('p.', $font, $brush, 5, 1)
$icon = [System.Drawing.Icon]::FromHandle($bitmap.GetHicon())
$iconPath = Join-Path $buildDir 'plano.ico'
$stream = [IO.File]::Create($iconPath)
try { $icon.Save($stream) } finally { $stream.Dispose(); $graphics.Dispose(); $font.Dispose(); $brush.Dispose(); $icon.Dispose(); $bitmap.Dispose() }
$output = Join-Path $projectRoot 'Plano.exe'
& $compiler /nologo /target:winexe /optimize+ /codepage:65001 "/out:$output" "/win32icon:$iconPath" /reference:System.Windows.Forms.dll /reference:System.Drawing.dll /reference:System.Web.Extensions.dll (Join-Path $PSScriptRoot 'Launcher.cs')
if ($LASTEXITCODE -ne 0) { throw 'Não foi possível gerar Plano.exe. Feche o iniciador antes de recompilar.' }
if ($CreateShortcut) {
    $desktopDir = [Environment]::GetFolderPath('DesktopDirectory')
    $shortcutPath = Join-Path $desktopDir 'Plano.lnk'
    $shellObject = New-Object -ComObject WScript.Shell
    if (Test-Path -LiteralPath $shortcutPath) {
        $existing = $shellObject.CreateShortcut($shortcutPath)
        if ($existing.TargetPath -ne $output) { throw 'Já existe outro atalho Plano na área de trabalho. O executável foi gerado; o atalho existente foi preservado.' }
    }
    $shortcut = $shellObject.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $output
    $shortcut.WorkingDirectory = $projectRoot
    $shortcut.IconLocation = "$output,0"
    $shortcut.Description = 'Abrir o controle de estudos e projetos Plano'
    $shortcut.Save()
    Write-Output "Atalho: $shortcutPath"
}
Write-Output "Executável: $output"
