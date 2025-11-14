# Plotinator 10k Windows Installer Guide

This guide covers freezing Plotinator 10k with
[PyInstaller](https://pyinstaller.org/) and wrapping the resulting bundle in a
Windows `.msi` installer using the WiX Toolset 3.11 toolchain. Perform the steps
on a Windows workstation so that native dependencies are captured correctly.

> **Tip:** Always start from a clean checkout on the target platform. PyInstaller
> embeds the Python runtime and the Windows DLLs that are present when you build.

## 1. Prerequisites

1. **Python** – Install Python 3.10 or newer and ensure `python`/`pip` resolve
   from the terminal.
2. **Runtime tooling** – Install the external binaries that Plotinator shells out
   to during execution:
   - [`gnuplot`](http://www.gnuplot.info/)
   - [`pandoc`](https://pandoc.org/)
   - [`wkhtmltopdf`](https://wkhtmltopdf.org/)

   Export their locations as environment variables before packaging so the
   PyInstaller spec can pick them up:

   ```powershell
   setx GNUPLOT_PATH "C:\\Program Files\\gnuplot\\bin\\gnuplot.exe"
   setx PANDOC_PATH "C:\\Program Files\\Pandoc\\pandoc.exe"
   setx WKHTMLTOPDF_PATH "C:\\Program Files\\wkhtmltopdf\\bin\\wkhtmltopdf.exe"
   ```

   Restart the terminal session after updating `setx` values.
3. **Python dependencies** – Install project extras alongside PyInstaller in an
   isolated environment:

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\activate
   python -m pip install --upgrade pip wheel
   python -m pip install .[yaml]
   python -m pip install pyinstaller pyinstaller-hooks-contrib
   ```
4. **WiX Toolset 3.11** – Download WiX Toolset v3.11.2.4516 from
   <https://wixtoolset.org/releases/v3.11.2.4516/wix311.exe> and install it to
   the default location (`C:\Program Files (x86)\WiX Toolset v3.11\`). The batch
   script in this repository invokes `candle.exe`/`light.exe` from that folder.

## 2. Build the PyInstaller bundle

The repository ships with a tailored spec at `packaging/plotinator.spec` that
produces all three entry points (CLI, GUI, and report helper) in a single
folder.

1. From the repository root, run PyInstaller against the spec:

   ```powershell
   pyinstaller packaging/plotinator.spec --clean --noconfirm
   ```

2. Inspect the output under `dist\plotinator-bundle` and confirm that it
   contains:
   - `plotinator-cli.exe`
   - `plotinator-gui.exe`
   - `plotinator-report.exe`
   - A `_internal\` folder with the bundled Python runtime and DLLs

3. Smoke-test the executables before proceeding:

   ```powershell
   .\dist\plotinator-bundle\plotinator-cli.exe --help
   .\dist\plotinator-bundle\plotinator-report.exe --help
   Start-Process .\dist\plotinator-bundle\plotinator-gui.exe
   ```

   Verify that `plotinator-gui.exe` launches, loads `config.json`, and can exit
   cleanly. If any tool fails to start, double-check that the corresponding
   external binary is present inside `dist\plotinator-bundle\_internal` and
   rebuild if necessary.

## 3. Generate WiX component markup

`packaging/windows/plotinator-files.wxs` must describe every executable and DLL
in the PyInstaller output. Regenerate it whenever the bundle changes. WiX 3.11's
`heat.exe` utility can harvest the files automatically:

```powershell
$bundle = Resolve-Path dist/plotinator-bundle
"C:\Program Files (x86)\WiX Toolset v3.11\bin\heat.exe" dir $bundle `
  -nologo `
  -cg PlotinatorFiles `
  -dr INSTALLFOLDER `
  -sreg -sfrag -scom -srd `
  -out packaging/windows/plotinator-files.wxs
```

Review the generated markup and ensure:

- Every `<Component>` uses a unique, stable `Guid` value.
- All components target `Directory="INSTALLFOLDER"` or a subdirectory beneath
  it.
- No component mixes 32-bit and 64-bit destinations.

Commit the regenerated file so that other machines can build the MSI without
re-harvesting.

## 4. Build the MSI installer

Run the batch script from `packaging/windows/` to compile the WiX sources with
WiX 3.11:

```powershell
cd packaging/windows
build-installer.bat
```

The script performs the following:

1. Compiles `plotinator.wxs` and `plotinator-files.wxs` with
   `candle.exe -dPLOTINATOR_VERSION=<version>`.
2. Links the resulting `.wixobj` files with `light.exe` (UI extension enabled).
3. Writes `dist/Plotinator_10k.msi` next to the PyInstaller bundle.

Update the `PRODUCT_VERSION` variable inside `build-installer.bat` whenever you
ship a new release so the MSI version matches the application.

## 5. Validate the installer

- Run the generated MSI on a clean Windows VM.
- Accept the default installation directory
  (`Program Files\Plotinator 10k`).
- Launch the installed shortcuts for the CLI, GUI, and report helper to confirm
  they find their dependencies.
- Uninstall via *Apps & Features* and verify the directory is removed.

## 6. Troubleshooting

| Symptom | Cause | Resolution |
| --- | --- | --- |
| `gnuplot` invocation fails or plots are missing after installation | `gnuplot` was absent when PyInstaller ran, so the executable was not copied into `_internal/` | Install `gnuplot`, update `GNUPLOT_PATH`, delete `build/` and `dist/`, then rebuild the PyInstaller bundle. |
| PDF export crashes with `pandoc: command not found` | `pandoc` or `wkhtmltopdf` were missing when PyInstaller executed | Install both tools, set the corresponding environment variables, and rebuild so the binaries appear in `_internal/`. |
| PyInstaller build log reports missing modules such as `plot_manager` | Hidden imports were not collected | Use the provided `packaging/plotinator.spec`; it already collects the `engine`, `config`, `plotinator`, and `reports` packages. Delete previous build artefacts before retrying. |
| `candle.exe` reports schema errors | WiX v4/v6 binaries are on `PATH` | Ensure `C:\Program Files (x86)\WiX Toolset v3.11\bin` appears **before** other WiX installations or update the batch script to point to the correct binaries. |
| `light.exe` fails with `LGHT0103` (file not found) | Incorrect path to `plotinator-files.wxs` or missing component entries | Confirm the file exists, that it contains the harvested components, and rerun `heat.exe` if necessary. |

Once the MSI passes validation, publish both the zipped `dist/plotinator-bundle`
folder and the `dist/Plotinator_10k.msi` package to your distribution
channel.
