@echo off
setlocal

set "PROJECT_DIR=%~dp0"
set "SOURCE_DIR=%PROJECT_DIR%..\..\dist\plotinator-bundle"
set "DIST_DIR=%PROJECT_DIR%..\..\dist"
set "WXS_MAIN=plotinator.wxs"
set "WXS_FILES=plotinator-files.wxs"
set "MSI_OUT=Plotinator_10k.msi"
set "PRODUCT_VERSION=1.0.0"

set "WIX_BIN=C:\Program Files (x86)\WiX Toolset v3.14\bin"

cd /d "%PROJECT_DIR%"

"%WIX_BIN%\candle.exe" ^
  -dPLOTINATOR_VERSION=%PRODUCT_VERSION% ^
  -dSourceDir="%SOURCE_DIR%" ^
  "%WXS_MAIN%" "%WXS_FILES%"

if %ERRORLEVEL% neq 0 (
  echo ERROR: candle.exe failed.
  goto :eof
)

"%WIX_BIN%\light.exe" -ext WixUIExtension ^
  -dSourceDir="%SOURCE_DIR%" ^
  -out "%DIST_DIR%\%MSI_OUT%" ^
  "plotinator.wixobj" "plotinator-files.wixobj"

if %ERRORLEVEL% neq 0 (
  echo ERROR: light.exe failed.
  goto :eof
)

echo SUCCESS: MSI created at "%DIST_DIR%\%MSI_OUT%"

endlocal
