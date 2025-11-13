@echo off
setlocal

rem — variables del proyecto
set "PROJECT_DIR=C:\Projects\Plotinator_10k\packaging\windows"
set "DIST_DIR=%PROJECT_DIR%..\..\dist"
set "WXS_MAIN=plotinator.wxs"
set "WXS_FILES=plotinator-files.wxs"
set "MSI_OUT=Plotinator_10k.msi"
set "PRODUCT_VERSION=1.0.0"

rem — carpeta bin del WiX v3 (ajusta ruta si es distinta)
set "WIX_BIN=C:\Program Files (x86)\WiX Toolset v3.14\bin"

rem — ir al directorio del proyecto
cd /d "%PROJECT_DIR%" || (
    echo ERROR: No se pudo cambiar al directorio %PROJECT_DIR%
    goto :eof
)

rem — compilar los archivos .wxs a .wixobj
"%WIX_BIN%\candle.exe" -dPLOTINATOR_VERSION=%PRODUCT_VERSION% -dSourceDir="..\..\dist\plotinator-bundle" "%WXS_MAIN%" "%WXS_FILES%"
if %ERRORLEVEL% neq 0 (
    echo ERROR: candle.exe falló.
    goto :eof
)

rem — verificar que los objetos .wixobj fueron generados
if not exist "%PROJECT_DIR%\plotinator.wixobj" (
    echo ERROR: No se encuentra plotinator.wixobj
    goto :eof
)
if not exist "%PROJECT_DIR%\plotinator-files.wixobj" (
    echo ERROR: No se encuentra plotinator-files.wixobj
    goto :eof
)

rem — unir y generar el .msi

"%WIX_BIN%\light.exe" -ext WixUIExtension -dSourceDir="..\..\dist\plotinator-bundle" -out "%DIST_DIR%\%MSI_OUT%" "plotinator.wixobj" "plotinator-files.wixobj"

if %ERRORLEVEL% neq 0 (
    echo ERROR: light.exe falló.
    goto :eof
)

echo Construcción completada: "%DIST_DIR%\%MSI_OUT%"

endlocal
