# Windows Packaging Assets

This folder contains helper assets for turning the PyInstaller output into a Windows MSI installer.

## Files

- `plotinator.wxs` – WiX authoring template that wraps the PyInstaller bundle. Replace the `UpgradeCode`
  value with a stable GUID the first time you ship an MSI.

## Usage Overview

1. **Freeze the application** using the shared PyInstaller spec:
   ```powershell
   pyinstaller packaging/plotinator.spec --clean --noconfirm
   ```
   The output folder `dist\plotinator-bundle` should contain the three executables and resource data.
2. **Harvest the bundle** into WiX component markup:
   ```powershell
   $bundle = Resolve-Path dist/plotinator-bundle
   New-Item -ItemType Directory -Force -Path packaging/windows/build | Out-Null
   wix harvest dir $bundle `
     -id PlotinatorBundleComponents `
     -ext WixToolset.Heat.wixext `
     -out packaging/windows/build/plotinator-files.wxs
   ```
3. **Build** the MSI using the template:
   ```powershell
   $version = (python -c "import plotinator; print(plotinator.__version__)").Trim()
   wix build `
     packaging/windows/plotinator.wxs `
     packaging/windows/build/plotinator-files.wxs `
     -ext WixToolset.UI.wixext `
     -out dist/Plotinator_OpenBeta-$version.msi `
     -dPLOTINATOR_VERSION=$version
   ```
4. **Verify the installer** by running it on a clean Windows VM and checking that the CLI, GUI, and
   report helpers launch from `Program Files\Plotinator Open Beta` without missing dependency errors.

For a fuller walkthrough that includes environment setup and validation steps, see `docs/INSTALLER.md`.
