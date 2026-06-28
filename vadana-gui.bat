@echo off
REM Vadana Extractor - desktop GUI launcher for Windows. Double-click to run.
setlocal
cd /d "%~dp0"
set "PYEXE="
for %%V in (3.13 3.12 3.11) do (
    if not defined PYEXE ( py -%%V -c "" >nul 2>nul && set "PYEXE=py -%%V" )
)
if not defined PYEXE ( where py >nul 2>nul && set "PYEXE=py" )
if not defined PYEXE ( set "PYEXE=python" )
%PYEXE% -c "import customtkinter" >nul 2>nul || ( echo Installing the GUI dependency... & %PYEXE% -m pip install customtkinter )
%PYEXE% "%~dp0gui\vadana_gui.py" %*
if errorlevel 1 pause
