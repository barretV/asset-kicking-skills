@echo off
rem pixelart - scriptable front end for a compiled Aseprite
rem Set ASEPRITE_PATH if the binary is not in the project's default build location.
where py >nul 2>&1
if %errorlevel%==0 (
  py -3 "%~dp0pixelart.py" %*
) else (
  python "%~dp0pixelart.py" %*
)
