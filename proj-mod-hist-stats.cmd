@echo off
setlocal ENABLEEXTENSIONS

REM Determine script directory
set "SCRIPT_DIR=%~dp0"

REM Prefer the workspace venv's python if it exists
set "PY=%SCRIPT_DIR%.venv\Scripts\python.exe"
if exist "%PY%" goto run

REM Fallback to py launcher, then python on PATH
where py >nul 2>nul
if %ERRORLEVEL%==0 (
  set "PY=py"
) else (
  set "PY=python"
)

:run
REM Help shortcuts
if /I "%~1"=="/?" goto :help
if /I "%~1"=="-?" goto :help
if /I "%~1"=="-h" goto :help
if /I "%~1"=="--help" goto :help

REM Determine ROOT and ARGS (avoid parentheses to keep expansions correct)
set "ROOT="
if "%~1"=="" goto :_set_root_cd
set "FIRST=%~1"
set "FIRSTCHR=%FIRST:~0,1%"
if "%FIRSTCHR%"=="-" goto :_set_root_cd
if "%FIRSTCHR%"=="/" goto :_set_root_cd
set "ROOT=%~1"
shift
goto :after_root

:_set_root_cd
set "ROOT=%CD%"
goto :after_root

:after_root

REM No filename prefix is used anymore; output name is <repo>_<branch>_<sha6>.csv

REM Optional debug: set PMH_DEBUG=1 to print the composed command
if /I "%PMH_DEBUG%"=="1" (
  echo PY: %PY%
  echo ROOT: "%ROOT%"
  echo ARGS: %*
  echo (no extra opts)
)

REM Call Python with original args preserved; avoid delayed expansion side-effects
"%PY%" "%SCRIPT_DIR%project-modification-history-statistics.py" "%ROOT%" %*
set "EXITCODE=%ERRORLEVEL%"
if not "%EXITCODE%"=="0" (
  echo Script exited with code %EXITCODE%.
)
exit /b %EXITCODE%

:help
echo Usage: %~n0 [ROOT_DIR] [options]
echo.
echo   ROOT_DIR  Path to the repo root ^(must contain .git^) ^(default: current directory^)
echo   options   Passed through to project-modification-history-statistics.py
echo.
echo Common options:
echo   -y N            Number of years to analyze ^(default: 10^)
echo   -o DIR          Output directory for CSV ^(default: script directory^)
echo   -i PATTERN      Ignore relative path patterns ^(glob; can repeat or comma-separate^)
echo   --project-type  Project types to include: .bproj, .csproj, .vcxproj ^(repeat or comma-separated^)
echo   --quiet ^| --verbose  Quiet or verbose mode ^(mutually exclusive; place last^)
echo.
echo Examples:
echo   %~n0                    - uses current directory
echo   %~n0 C:\path\to\repo -y 5 -o C:\outdir -i src/Legacy -i "tests/*" --verbose
echo   %~n0 --project-type .csproj,.vcxproj --verbose
exit /b 0
