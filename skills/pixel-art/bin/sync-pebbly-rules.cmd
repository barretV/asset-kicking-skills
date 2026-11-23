@echo off
setlocal
set ROOT=%~dp0..
set TMP=%ROOT%\_pebbly-sparse
set DEST=%ROOT%\knowledge\rules

if exist "%TMP%" rmdir /s /q "%TMP%"
git clone --depth 1 --filter=blob:none --sparse https://github.com/with-pebbly/aseprite-ai-artist.git "%TMP%"
if errorlevel 1 exit /b 1
pushd "%TMP%"
git sparse-checkout set rules
popd
if not exist "%DEST%" mkdir "%DEST%"
xcopy /e /y /i "%TMP%\rules\*" "%DEST%\"
rmdir /s /q "%TMP%"
echo Updated rules in %DEST%
