# Plotinator 10k Installer Guide

This guide describes how to freeze the Plotinator 10k toolkit with [PyInstaller](https://pyinstaller.org/) and how to wrap the
resulting bundle in a Windows `.msi` installer using the [WiX Toolset](https://wixtoolset.org/). Follow the steps in order on a
Windows machine so that native dependencies are captured correctly.

> **Tip:** Always start from a clean checkout on the target platform. PyInstaller in particular embeds the Python runtime and
> system DLLs that are present when you build.

## 1. Prerequisites

1. **Python** – Install Python 3.10 or newer and ensure `python`/`pip` resolve from the terminal.
2. **Runtime tooling** – Install the external binaries that Plotinator shells out to during execution:
   - [`gnuplot`](http://www.gnuplot.info/)
   - [`pandoc`](https://pandoc.org/)
   - [`wkhtmltopdf`](https://wkhtmltopdf.org/)
   Export their locations as environment variables before packaging so the PyInstaller spec can pick them up:
   ```powershell
   setx GNUPLOT_PATH "C:\\Program Files\\gnuplot\\bin\\gnuplot.exe"
   setx PANDOC_PATH "C:\\Program Files\\Pandoc\\pandoc.exe"
   setx WKHTMLTOPDF_PATH "C:\\Program Files\\wkhtmltopdf\\bin\\wkhtmltopdf.exe"
   ```
   Restart the terminal session after updating `setx` values.
3. **Python dependencies** – Install project extras alongside PyInstaller in an isolated environment:
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\activate
   python -m pip install --upgrade pip wheel
   python -m pip install .[yaml]
   python -m pip install pyinstaller pyinstaller-hooks-contrib
   ```
4. **WiX Toolset** – Download WiX 3.14+ and either add `%WIX%\bin` to `PATH` or reference the absolute binary paths when running
   `heat.exe`, `candle.exe`, and `light.exe`.

## 2. Build the PyInstaller bundle

The repository ships with a tailored spec at `packaging/plotinator.spec` that produces all three entry points (CLI, GUI, and report
helper) in a single folder.

1. From the repository root, run PyInstaller against the spec:
   ```powershell
   pyinstaller packaging/plotinator.spec --clean --noconfirm
   ```
2. Inspect the output under `dist\plotinator-bundle` and confirm that it contains:
   - `plotinator-cli.exe`
   - `plotinator-gui.exe`
   - `plotinator-report.exe`
   - A `data\` folder with the sample `.dat` files
   - An `external\` folder with the detected `gnuplot`, `pandoc`, and `wkhtmltopdf` executables
3. Smoke-test the executables before proceeding:
   ```powershell
   .\dist\plotinator-bundle\plotinator-cli.exe --help
   .\dist\plotinator-bundle\plotinator-report.exe --help
   Start-Process .\dist\plotinator-bundle\plotinator-gui.exe
   ```
   Verify that `plotinator-gui.exe` launches, loads `config.json`, and can exit cleanly. If any tool fails to start, double-check
   that the corresponding external binary is present inside `dist\plotinator-bundle\external` and rebuild if necessary.

## 3. Author the MSI installer

MSI authoring assets live under `packaging/windows/`. The folder contains a WiX template (`plotinator.wxs`) and documentation for
collecting files from the PyInstaller bundle.

1. **Harvest** the PyInstaller output into a component description using WiX `heat`:
   ```powershell
   $bundle = Resolve-Path dist/plotinator-bundle
   New-Item -ItemType Directory -Force -Path packaging/windows/build | Out-Null
   heat dir $bundle `
     -dr APPLICATIONFOLDER `
     -cg PlotinatorBundleComponents `
     -gg `
     -sfrag `
     -srd `
     -out packaging/windows/build/plotinator-files.wxs
   ```
   The generated file is referenced by the template via `<ComponentGroupRef Id="PlotinatorBundleComponents" />`.
2. **Compile** the WiX sources with the correct version metadata:
   ```powershell
   $version = (python -c "import plotinator; print(plotinator.__version__)").Trim()
   $wixOut = Resolve-Path packaging/windows/build
   candle packaging/windows/plotinator.wxs $wixOut/plotinator-files.wxs `
     -dPLOTINATOR_VERSION=$version `
     -out $wixOut/
   ```
   Replace the placeholder `UpgradeCode` in `plotinator.wxs` with a stable GUID before the first production release.
3. **Link** the compiled objects into a distributable MSI:
   ```powershell
   light $wixOut/plotinator.wixobj $wixOut/plotinator-files.wixobj `
     -ext WixUIExtension `
     -cultures:en-us `
     -o dist/plotinator-$version.msi
   ```
4. **Verify** the installer on a clean Windows environment:
   - Run the MSI and choose the default installation directory.
   - Confirm the binaries are placed under `Program Files\Plotinator 10k`.
   - Launch the installed `Plotinator GUI` shortcut and trigger a sample batch run using the bundled `data\` files.
   - Generate a PDF report via `Plotinator Report Helper` to ensure `pandoc`/`wkhtmltopdf` were correctly captured.

## 4. Packaging Troubleshooting

| Symptom | Cause | Resolution |
| --- | --- | --- |
| `gnuplot` invocation fails or plots are missing after installation | `gnuplot` was absent when PyInstaller ran, so the executable was not copied into `external/` | Install `gnuplot`, update `GNUPLOT_PATH`, delete `build/` and `dist/`, then rebuild the PyInstaller bundle. |
| PDF export crashes with `pandoc: command not found` | `pandoc` or `wkhtmltopdf` were missing when PyInstaller executed | Install both tools, set the corresponding environment variables, and rebuild so the binaries appear in `external/`. |
| PyInstaller build log reports missing modules such as `plot_manager` | Hidden imports were not collected | Use the provided `packaging/plotinator.spec`; it already collects the `engine`, `config`, `plotinator`, and `reports` packages. Delete previous build artefacts before retrying. |
| `light.exe` fails with `LGHT0103` (file not found) | Incorrect path to the harvested WiX file or WiX binaries | Ensure `%WIX%` is configured or invoke `heat`, `candle`, and `light` with absolute paths. Verify `packaging/windows/build/plotinator-files.wxs` exists. |
| Installer launches but the app immediately exits | Missing Visual C++ runtime on the target machine | Install the [Microsoft Visual C++ Redistributable for VS 2015-2022](https://aka.ms/vs/17/release/vc_redist.x64.exe) before running Plotinator. |

Once the MSI passes validation, publish both the zipped `dist/plotinator-bundle` folder and the MSI to your distribution channel.
