#!/bin/sh
:; exec sh "$(cd "$(dirname "$0")" && pwd)/session-context.sh"
@powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0session-context.ps1"
