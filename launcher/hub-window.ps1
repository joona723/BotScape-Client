# Edge --app uses the favicon but can retain Edge's taskbar identity. Give only
# this install's dedicated browser process the hub icon and shell relaunch data.
param([Parameter(Mandatory=$true)][string]$Root)
$ErrorActionPreference = 'Stop'
Add-Type -Path (Join-Path $PSScriptRoot 'HubWindow.cs')
$profileArgument = '--user-data-dir=' + (Join-Path $Root '.launcher-window')
$icon = Join-Path $Root 'assets\brand\hub.ico'
$exe = Join-Path $Root 'BotScape.exe'
# A source checkout can launch LAUNCHER.pyw directly, before packaging the exe.
if (-not (Test-Path -LiteralPath $exe)) {
    $exe = Join-Path $Root 'launcher\stub\bin\Release\net48\BotScape.exe'
}
$browserId = 0
for ($attempt = 0; $attempt -lt 30 -and -not $browserId; $attempt++) {
    # Match the complete profile argument, not another checkout's hub or normal Edge.
    $browser = Get-CimInstance Win32_Process -Filter "Name='msedge.exe'" |
        Where-Object { $_.CommandLine -and
            ($_.CommandLine.Contains('"' + $profileArgument + '"') -or
             ($_.CommandLine -split ' ') -contains $profileArgument) -and
            $_.CommandLine -notmatch '--type=' } | Select-Object -First 1
    if ($browser) { $browserId = [int]$browser.ProcessId }
    else { Start-Sleep -Milliseconds 500 }
}
if (-not $browserId) { exit }
# Keep HICONs alive and reapply after Edge navigation / DPI changes. New hub
# windows handed to this browser process receive the same identity too.
while (Get-Process -Id $browserId -ErrorAction SilentlyContinue) {
    [void][BotScape.HubWindow]::ApplyToProcess($browserId, $icon, $exe)
    Start-Sleep -Seconds 2
}
