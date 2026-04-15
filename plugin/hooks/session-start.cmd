#!/bin/sh
:; exec bash "$(cd "$(dirname "$0")" && pwd)/install-dependencies.sh"
@powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-dependencies.ps1"
