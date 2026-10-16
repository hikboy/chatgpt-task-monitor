#requires -Version 5.1
# Compatibility entry point for the earlier Windows setup. Logic lives in Python.
[CmdletBinding()]
param(
    [Parameter(Position = 0)] [string] $EventJson,
    [switch] $DryRun,
    [switch] $SkipOriginal,
    [switch] $PassThru
)
$ErrorActionPreference = 'Stop'
$showResult = $PassThru -or $DryRun
try {
    $notificationHome = if ([string]::IsNullOrWhiteSpace($env:CODEX_HOME)) {
        Join-Path $env:USERPROFILE '.codex'
    } else { $env:CODEX_HOME }
    $notificationDirectory = Join-Path $notificationHome 'notifications\codex-telegram'
    $runtime = Get-Content -LiteralPath (Join-Path $notificationDirectory 'runtime.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if (-not (Test-Path -LiteralPath $runtime.python -PathType Leaf)) { throw 'python-runtime-unavailable' }
    $arguments = @((Join-Path $notificationDirectory 'codex_telegram.py'), '--codex-home', $notificationHome, 'notify', '--stdin')
    if ($DryRun) { $arguments += '--dry-run' }
    if ($SkipOriginal) { $arguments += '--skip-original' }
    if ($showResult) { $arguments += '--json' }
    # stdin avoids Windows PowerShell's native-argument escaping of JSON quotes.
    $previousEncoding = $OutputEncoding
    try {
        $OutputEncoding = [Text.UTF8Encoding]::new($false)
        $response = $EventJson | & $runtime.python @arguments
        if ($LASTEXITCODE -ne 0) { throw 'python-callback-failed' }
    } finally { $OutputEncoding = $previousEncoding }
    if ($showResult) { $response | Out-String | ConvertFrom-Json }
} catch {
    if ($showResult) { [pscustomobject]@{ success = $false; status = 'notification-launch-failed' } }
}
