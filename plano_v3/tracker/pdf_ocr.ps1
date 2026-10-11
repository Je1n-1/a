param([Parameter(Mandatory=$true)][string]$PdfPath)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType=WindowsRuntime]
$null = [Windows.Data.Pdf.PdfDocument, Windows.Data.Pdf, ContentType=WindowsRuntime]
$null = [Windows.Storage.Streams.InMemoryRandomAccessStream, Windows.Storage.Streams, ContentType=WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType=WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType=WindowsRuntime]
$null = [Windows.Globalization.Language, Windows.Globalization, ContentType=WindowsRuntime]
$generic = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.IsGenericMethodDefinition -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' } | Select-Object -First 1
$action = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and -not $_.IsGenericMethod -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncAction' } | Select-Object -First 1
function Await-Operation($Operation, [Type]$ResultType) {
    $task = $generic.MakeGenericMethod($ResultType).Invoke($null, @($Operation))
    $task.GetAwaiter().GetResult()
}
try {
    $language = New-Object Windows.Globalization.Language('pt-BR')
    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($language)
    if ($null -eq $engine) { throw 'OCR_PORTUGUESE_UNAVAILABLE' }
    $file = Await-Operation ([Windows.Storage.StorageFile]::GetFileFromPathAsync($PdfPath)) ([Windows.Storage.StorageFile])
    $pdf = Await-Operation ([Windows.Data.Pdf.PdfDocument]::LoadFromFileAsync($file)) ([Windows.Data.Pdf.PdfDocument])
    if ($pdf.PageCount -gt 12) { throw 'OCR_PAGE_LIMIT' }
    $pages = @()
    for ($index = 0; $index -lt $pdf.PageCount; $index++) {
        $page = $pdf.GetPage($index)
        $stream = New-Object Windows.Storage.Streams.InMemoryRandomAccessStream
        $bitmap = $null
        try {
            $options = New-Object Windows.Data.Pdf.PdfPageRenderOptions
            $scale = [Math]::Min(3300, [Windows.Media.Ocr.OcrEngine]::MaxImageDimension) / [Math]::Max($page.Size.Width, $page.Size.Height)
            $options.DestinationWidth = [uint32][Math]::Floor($page.Size.Width * $scale)
            $options.DestinationHeight = [uint32][Math]::Floor($page.Size.Height * $scale)
            $task = $action.Invoke($null, @($page.RenderToStreamAsync($stream, $options)))
            $null = $task.GetAwaiter().GetResult()
            $stream.Seek(0)
            $decoder = Await-Operation ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
            $bitmap = Await-Operation ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
            $result = Await-Operation ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
            $words = @()
            foreach ($line in $result.Lines) {
                foreach ($word in $line.Words) {
                    $r = $word.BoundingRect
                    $words += @{text=$word.Text; x=$r.X; y=$r.Y; width=$r.Width; height=$r.Height}
                }
            }
            $pages += @{page=$index+1; width=$options.DestinationWidth; height=$options.DestinationHeight; words=$words}
        } finally {
            if ($null -ne $bitmap) { $bitmap.Dispose() }
            $stream.Dispose()
            $page.Dispose()
        }
    }
    @{pages=$pages; language=$engine.RecognizerLanguage.LanguageTag} | ConvertTo-Json -Depth 7 -Compress
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
