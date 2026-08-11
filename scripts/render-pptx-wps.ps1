param(
  [Parameter(Mandatory = $true)][string]$InputFile,
  [Parameter(Mandatory = $true)][string]$OutputDirectory
)

$ErrorActionPreference = "Stop"
$source = (Resolve-Path -LiteralPath $InputFile).Path
$output = [IO.Path]::GetFullPath($OutputDirectory)
[IO.Directory]::CreateDirectory($output) | Out-Null

$application = $null
$presentation = $null
try {
  $application = New-Object -ComObject "KWPP.Application"
  # WPS rejects Visible=false on some builds. Opening without a presentation
  # window keeps the automation headless without relying on that property.
  $presentation = $application.Presentations.Open($source, $true, $true, $false)
  $slideCount = $presentation.Slides.Count
  for ($index = 1; $index -le $slideCount; $index++) {
    $target = Join-Path $output ("slide-{0}.png" -f $index)
    $presentation.Slides.Item($index).Export($target, "PNG", 1280, 720)
  }
  [pscustomobject]@{ slideCount = $slideCount; outputDirectory = $output } |
    ConvertTo-Json -Compress
}
finally {
  if ($presentation) {
    $presentation.Close()
    [void][Runtime.InteropServices.Marshal]::ReleaseComObject($presentation)
  }
  if ($application) {
    $application.Quit()
    [void][Runtime.InteropServices.Marshal]::ReleaseComObject($application)
  }
  [GC]::Collect()
  [GC]::WaitForPendingFinalizers()
}
