# Windows MSI Packaging Checklist

This folder contains the WiX sources and helper script required to turn the
PyInstaller output into a repeatable MSI installer on **any** Windows machine.
Follow the steps below without deviation to avoid schema or toolchain issues.

## 1. Install WiX 3.11

Only WiX Toolset **v3.11.2.4516** works with the current authoring. Later
versions (v4/v6) use incompatible schemas and will not build this project.
Download and install:

<https://wixtoolset.org/releases/v3.11.2.4516/wix311.exe>

The installer places the binaries under
`C:\Program Files (x86)\WiX Toolset v3.11\bin`. The batch script assumes this
exact path.

## 2. Prepare the repository layout

Ensure the repository matches the following structure on disk (PyInstaller
outputs live in `dist/plotinator-bundle`):

```
Plotinator_10k/
 ├─ dist/
 │   └─ plotinator-bundle/
 │        ├─ plotinator-cli.exe
 │        ├─ plotinator-gui.exe
 │        ├─ plotinator-report.exe
 │        └─ _internal/ (all DLLs)
 └─ packaging/
      └─ windows/
            plotinator.wxs
            plotinator-files.wxs
            build-installer.bat
            plotinator.ico (optional)
```

Generate `plotinator-files.wxs` using WiX `heat.exe` after building the
PyInstaller bundle. The template in this repository documents the expected
command line—replace the placeholder markup with the harvested components and
commit the result so it can be reused on every build workstation.

## 3. Build the MSI

From `packaging/windows/`, run the provided batch script:

```
build-installer.bat
```

The script compiles `plotinator.wxs` and `plotinator-files.wxs` with WiX 3.11
(`candle.exe` + `light.exe`) and writes `dist/Plotinator_10k.msi`. The default
version embedded in the MSI is `1.0.0`; adjust `PRODUCT_VERSION` inside the
batch file before releasing a new build.

## 4. Release checklist

- [ ] `plotinator.wxs` retains the UpgradeCode
  `A1C3D9E4-5B27-41F8-9C71-2F91BBAC7E54` (no braces).
- [ ] Every component in `plotinator-files.wxs` targets `INSTALLFOLDER` (the
      64-bit `ProgramFiles64Folder`).
- [ ] Each `<Component>` in `plotinator-files.wxs` uses a unique, stable `Guid`.
- [ ] The PyInstaller bundle includes all executables and dependency DLLs.
- [ ] `build-installer.bat` completes successfully and prints the MSI path.

When all boxes are checked, the resulting MSI installs Plotinator 10k into
`Program Files\Plotinator 10k` with the expected shortcuts and binaries.
