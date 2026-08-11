param(
    [Parameter(Mandatory = $true)]
    [string]$ImagePath
)

$ErrorActionPreference = "Stop"
$resolvedPath = (Resolve-Path -LiteralPath $ImagePath).Path

Add-Type -AssemblyName System.Runtime.WindowsRuntime
[void][Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
[void][Windows.Storage.FileAccessMode, Windows.Storage, ContentType = WindowsRuntime]
[void][Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType = WindowsRuntime]
[void][Windows.Graphics.Imaging.SoftwareBitmap, Windows.Graphics.Imaging, ContentType = WindowsRuntime]
[void][Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
[void][Windows.Media.Ocr.OcrResult, Windows.Foundation, ContentType = WindowsRuntime]

function Await-WinRtOperation {
    param(
        [Parameter(Mandatory = $true)]$Operation,
        [Parameter(Mandatory = $true)][Type]$ResultType
    )

    $asTaskMethod = [System.WindowsRuntimeSystemExtensions].GetMethods() |
        Where-Object {
            $_.Name -eq "AsTask" -and
            $_.IsGenericMethodDefinition -and
            $_.GetGenericArguments().Count -eq 1 -and
            $_.GetParameters().Count -eq 1
        } |
        Select-Object -First 1
    if (-not $asTaskMethod) {
        throw "Unable to resolve WinRT AsTask adapter"
    }
    $task = $asTaskMethod.MakeGenericMethod($ResultType).Invoke($null, @($Operation))
    $task.GetAwaiter().GetResult()
}

$file = Await-WinRtOperation `
    ([Windows.Storage.StorageFile]::GetFileFromPathAsync($resolvedPath)) `
    ([Windows.Storage.StorageFile])
$stream = Await-WinRtOperation `
    ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) `
    ([Windows.Storage.Streams.IRandomAccessStream])
$decoder = Await-WinRtOperation `
    ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) `
    ([Windows.Graphics.Imaging.BitmapDecoder])
$bitmap = Await-WinRtOperation `
    ($decoder.GetSoftwareBitmapAsync()) `
    ([Windows.Graphics.Imaging.SoftwareBitmap])

$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
if (-not $engine) {
    throw "Windows OCR has no installed recognition language"
}
$result = Await-WinRtOperation `
    ($engine.RecognizeAsync($bitmap)) `
    ([Windows.Media.Ocr.OcrResult])

@{
    text = $result.Text
    lineCount = @($result.Lines).Count
} | ConvertTo-Json -Compress
