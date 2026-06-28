@echo off
REM Vadana Extractor — one-click interactive launcher for Windows.
REM Double-click this file, or run  vadana.bat  from a terminal.
setlocal
cd /d "%~dp0"
where python >nul 2>nul && (
    python "%~dp0cli\vadana.py" %*
) || (
    py "%~dp0cli\vadana.py" %*
)
echo.
pause
