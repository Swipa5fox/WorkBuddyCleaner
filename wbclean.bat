@echo off
rem ============================================================
rem  wbclean launcher (Windows)
rem
rem  Double-click this file to open the interactive menu.
rem  Everything user-visible is printed by the Python script,
rem  so this launcher stays ASCII-only on purpose: a .bat with
rem  Chinese text inside gets mangled by the OEM code page
rem  before chcp 65001 takes effect.
rem ============================================================

chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion

set "SCRIPT_DIR=%~dp0"
set "WBCLEAN=%SCRIPT_DIR%bin\wbclean"

if not exist "%WBCLEAN%" (
    echo.
    echo   [ERROR] bin\wbclean not found next to this launcher.
    echo   Expected: %WBCLEAN%
    echo.
    pause
    exit /b 1
)

rem ---- locate a usable Python 3.7+
set "PY_CMD="

py -3 -c "import sys; sys.exit(0 if sys.version_info>=(3,7) else 1)" >nul 2>&1
if not errorlevel 1 set "PY_CMD=py -3"

if not defined PY_CMD (
    python -c "import sys; sys.exit(0 if sys.version_info>=(3,7) else 1)" >nul 2>&1
    if not errorlevel 1 set "PY_CMD=python"
)

rem ---- fall back to the interpreter bundled with WorkBuddy
if not defined PY_CMD (
    if exist "%USERPROFILE%\.workbuddy\binaries\python\versions" (
        for /d %%D in ("%USERPROFILE%\.workbuddy\binaries\python\versions\*") do (
            if exist "%%D\python.exe" set "PY_CMD=%%D\python.exe"
        )
    )
)

if not defined PY_CMD (
    echo.
    echo   [ERROR] Python 3.7+ not found.
    echo.
    echo   Install it from https://www.python.org/downloads/windows/
    echo   and tick "Add python.exe to PATH" during setup.
    echo.
    pause
    exit /b 1
)

%PY_CMD% "%WBCLEAN%" menu
set "RC=%ERRORLEVEL%"

echo.
pause
exit /b %RC%
