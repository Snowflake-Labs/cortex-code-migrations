# Copyright 2026 Snowflake Inc.
# SPDX-License-Identifier: Apache-2.0
#
# UserPromptSubmit hook (Windows) — see session-context.sh for full rationale.
# Injects, ONCE per session, whether a migration project exists here plus
# routing guidance, on the user's first message. UserPromptSubmit reaches the
# model (SessionStart additionalContext does not, in coco).

$stdin = ""
try { $stdin = [Console]::In.ReadToEnd() } catch {}

$sid = ""
if ($stdin -match '"session_id"\s*:\s*"([^"]*)"') { $sid = $Matches[1] }

$markerDir = Join-Path ([System.IO.Path]::GetTempPath()) 'scai-migration-ctx'
$marker = ""
if ($sid) {
  $marker = Join-Path $markerDir $sid
  if (Test-Path $marker) { exit 0 }
} elseif ($stdin -match '"response_metadata"') {
  exit 0
}

$dir = $PWD.Path
if ($stdin -match '"cwd"\s*:\s*"([^"]*)"') { $dir = $Matches[1] -replace '\\\\', '\' }

if (Test-Path (Join-Path $dir '.scai/config/project.yml')) {
  Write-Output "<system-reminder>"
  Write-Output "[snowflake-migration] A migration project exists in this directory (.scai/config/project.yml)."
  Write-Output "- If the user's message names a specific migration task, or says ""continue""/""resume""/""next"": act on it by reading the built-in snowflake-migration:migration skill."
  Write-Output "- If the message is vague (e.g. ""help"", ""can you help me migrate""): ask ""What would you like to do today? Say 'continue' to pick up your migration where we left off, or tell me something specific."""
  Write-Output "- Otherwise, match the request to the relevant migration skill."
  Write-Output "</system-reminder>"
} else {
  Write-Output "<system-reminder>"
  Write-Output "[snowflake-migration] No migration project exists in this directory yet (no .scai/config/project.yml)."
  Write-Output "- To start or continue a migration here: read the built-in snowflake-migration:migration skill and follow its setup flow."
  Write-Output "- Otherwise, match the request to the relevant skill."
  Write-Output "</system-reminder>"
}

if ($marker) {
  New-Item -ItemType Directory -Force -Path $markerDir | Out-Null
  New-Item -ItemType File -Force -Path $marker | Out-Null
}
