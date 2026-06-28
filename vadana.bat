@echo off
REM Vadana Extractor - one-click interactive launcher for Windows.
REM Double-click this file, or run  vadana.bat  from a terminal.
setlocal
cd /d "%~dp0"
set "PYEXE="
for %%V in (3.13 3.12 3.11) do (
    if not defined PYEXE ( py -%%V -c "" >nul 2>nul && set "PYEXE=py -%%V" )
)
if not defined PYEXE ( where py >nul 2>nul && set "PYEXE=py" )
if not defined PYEXE ( set "PYEXE=python" )
%PYEXE% "%~dp0cli\vadana.py" %*
echo.
pause
