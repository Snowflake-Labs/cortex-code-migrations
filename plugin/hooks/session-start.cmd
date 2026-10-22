:; set -e; d="$(cd "$(dirname "$0")" && pwd)"; bash "$d/install-dependencies.sh"; exec sh "$d/validate-scai-mcp.sh"
@echo off
@powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-dependencies.ps1"
@if errorlevel 1 exit /b %errorlevel%
@powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0validate-scai-mcp.ps1"
@if errorlevel 1 exit /b %errorlevel%
