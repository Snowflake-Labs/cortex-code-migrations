$ErrorActionPreference = 'Stop'

$scriptDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
$hook = Join-Path (Split-Path -Parent $scriptDirectory) 'session-context.ps1'
$devReminder = Join-Path (Split-Path -Parent $scriptDirectory) 'dev-build-reminder.txt'
$testRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("session-context-test-" + [guid]::NewGuid())
New-Item -ItemType Directory -Path $testRoot | Out-Null

function Fail([string]$message) {
  throw "FAIL: $message"
}

function Invoke-Hook([string]$buildChannel, [string]$sessionId, [bool]$compactManifest = $false) {
  $pluginRoot = Join-Path $testRoot "plugin-$buildChannel"
  $manifestDirectory = Join-Path $pluginRoot '.cortex-plugin'
  New-Item -ItemType Directory -Path $manifestDirectory -Force | Out-Null
  New-Item -ItemType Directory -Path (Join-Path $pluginRoot 'hooks') -Force | Out-Null
  $manifest = if ($buildChannel -eq 'none') {
    '{"name":"snowflake-migration"}'
  } elseif ($compactManifest) {
    "{`"name`":`"snowflake-migration`",`"buildChannel`":`"$buildChannel`",`"version`":`"1.0.0`"}"
  } else {
    "{`"buildChannel`":`"$buildChannel`"}"
  }
  Set-Content -NoNewline -Path (Join-Path $manifestDirectory 'plugin.json') -Value $manifest
  Copy-Item $devReminder (Join-Path $pluginRoot 'hooks/dev-build-reminder.txt')
  $markerDirectory = Join-Path $testRoot "markers-$sessionId"
  New-Item -ItemType Directory -Path $markerDirectory -Force | Out-Null
  $previousPluginRoot = $env:CLAUDE_PLUGIN_ROOT
  $previousTempDirectory = $env:TMPDIR
  try {
    $env:CLAUDE_PLUGIN_ROOT = $pluginRoot
    $env:TMPDIR = $markerDirectory
    return ('{"session_id":"' + $sessionId + '","cwd":"' + $testRoot + '"}' | pwsh -NoProfile -File $hook)
  } finally {
    $env:CLAUDE_PLUGIN_ROOT = $previousPluginRoot
    $env:TMPDIR = $previousTempDirectory
  }
}

try {
  $devOutput = (Invoke-Hook 'dev' 'dev-session') -join "`n"
  if ($devOutput -notmatch 'Do not work around plugin bugs\.') {
    Fail 'dev manifest did not inject the bug guardrail'
  }

  $compactDevOutput = (Invoke-Hook 'dev' 'compact-dev-session' $true) -join "`n"
  if ($compactDevOutput -notmatch 'Do not work around plugin bugs\.') {
    Fail 'compact dev manifest did not inject the bug guardrail'
  }

  $previewOutput = (Invoke-Hook 'preview' 'preview-session') -join "`n"
  if ($previewOutput -match 'Do not work around plugin bugs\.') {
    Fail 'preview manifest injected the bug guardrail'
  }

  $noChannelOutput = (Invoke-Hook 'none' 'no-channel-session') -join "`n"
  if ($noChannelOutput -match 'Do not work around plugin bugs\.') {
    Fail 'manifest without buildChannel injected the bug guardrail'
  }

  Write-Output 'session-context.ps1 tests passed'
} finally {
  Remove-Item -Recurse -Force $testRoot
}
