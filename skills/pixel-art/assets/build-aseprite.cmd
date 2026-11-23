@echo off
rem Non-interactive Aseprite build (MSVC + Ninja + aseprite/skia m124)
rem Copy this file to the repo root next to aseprite\ and deps\skia\, then run:
rem   cmd /c build-aseprite.cmd
rem Override SKIA_DIR if the prebuilt Skia lives elsewhere.
setlocal
set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
set "PATH=%LOCALAPPDATA%\Microsoft\WinGet\Links;%PATH%"
if not defined SKIA_DIR set "SKIA_DIR=%ROOT%\deps\skia"

set "VSWHERE=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
set "VSDIR="
if exist "%VSWHERE%" (
  for /f "usebackq tokens=*" %%i in (`"%VSWHERE%" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath`) do set "VSDIR=%%i"
)
if not defined VSDIR (
  if exist "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat" set "VSDIR=C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools"
)
if not defined VSDIR (
  if exist "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat" set "VSDIR=C:\Program Files\Microsoft Visual Studio\2022\Community"
)
if not defined VSDIR (echo [ERROR] Visual Studio C++ tools not found & exit /b 1)

call "%VSDIR%\VC\Auxiliary\Build\vcvars64.bat" >nul 2>&1
where cl.exe >nul 2>&1 || (echo [ERROR] cl.exe not on PATH after vcvars & exit /b 1)
where ninja.exe >nul 2>&1 || (echo [ERROR] ninja not found - winget install Ninja-build.Ninja & exit /b 1)

cd /d "%ROOT%\aseprite"
if not exist build mkdir build
cd build

cmake -G Ninja ^
  -DCMAKE_BUILD_TYPE=RelWithDebInfo ^
  -DLAF_BACKEND=skia ^
  -DCMAKE_IGNORE_PATH=C:\MinGW\bin;C:\msys64\mingw64\bin ^
  -DSKIA_DIR="%SKIA_DIR%" ^
  -DSKIA_LIBRARY_DIR="%SKIA_DIR%\out\Release-x64" ^
  -DSKIA_LIBRARY="%SKIA_DIR%\out\Release-x64\skia.lib" ^
  ..
if errorlevel 1 goto :fail

ninja aseprite
if errorlevel 1 goto :fail

echo.
echo BUILD OK -^> %ROOT%\aseprite\build\bin\aseprite.exe
exit /b 0

:fail
echo.
echo BUILD FAILED (see output above)
exit /b 1
