# 打包成免安装单文件 exe
#
#   pwsh -File packaging\build.ps1              # 单文件（默认）
#   pwsh -File packaging\build.ps1 -Onedir      # 目录版（启动更快，便于排查）
#
# 产物一律落在 build\（已在 .gitignore 里），本目录只放打包脚本与图标。
param(
    [switch]$Onedir
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "找不到虚拟环境: $python" }

$icon = Join-Path $PSScriptRoot "app.ico"
if (-not (Test-Path $icon)) {
    Write-Host "== 生成图标 =="
    & $python (Join-Path $PSScriptRoot "make_icon.py")
}

$mode = if ($Onedir) { "--onedir" } else { "--onefile" }
$args = @(
    "--noconfirm", "--clean", $mode,
    "--windowed",
    # UPX 压缩省不了多少体积，却经常触发杀软误报，直接关掉
    "--noupx",
    "--name", "DrawX",
    "--icon", $icon,
    "--paths", (Join-Path $root "src"),
    "--distpath", (Join-Path $root "build\dist"),
    "--workpath", (Join-Path $root "build\pyi"),
    "--specpath", (Join-Path $root "build"),
    # 只用到 QtCore / QtGui / QtWidgets，其余一概不打包
    "--exclude-module", "PySide6.QtQml",
    "--exclude-module", "PySide6.QtQuick",
    "--exclude-module", "PySide6.QtQuickControls2",
    "--exclude-module", "PySide6.QtQuickWidgets",
    "--exclude-module", "PySide6.QtSql",
    "--exclude-module", "PySide6.QtTest",
    "--exclude-module", "PySide6.QtHelp",
    "--exclude-module", "PySide6.QtDesigner",
    "--exclude-module", "PySide6.QtUiTools",
    "--exclude-module", "PySide6.QtPrintSupport",
    "--exclude-module", "PySide6.QtOpenGL",
    "--exclude-module", "PySide6.QtOpenGLWidgets",
    "--exclude-module", "PySide6.QtSvgWidgets",
    "--exclude-module", "PySide6.QtNetwork",
    "--exclude-module", "PySide6.QtXml",
    "--exclude-module", "tkinter",
    "--exclude-module", "unittest",
    "--exclude-module", "pydoc",
    "--exclude-module", "numpy",
    "--exclude-module", "pandas",
    "--exclude-module", "matplotlib",
    "--exclude-module", "PyQt5",
    "--exclude-module", "PyQt6",
    (Join-Path $root "run.py")
)

Write-Host "== PyInstaller $mode =="
& $python -m PyInstaller @args
if ($LASTEXITCODE -ne 0) { throw "打包失败，退出码 $LASTEXITCODE" }

$exe = Join-Path $root "build\dist\DrawX.exe"
if (Test-Path $exe) {
    $size = [math]::Round((Get-Item $exe).Length / 1MB, 1)
    Write-Host ""
    Write-Host "================ 打包完成 ================"
    Write-Host "产物: $exe"
    Write-Host "体积: $size MB"
} else {
    $dir = Join-Path $root "build\dist\DrawX"
    Write-Host "产物目录: $dir"
    Get-ChildItem $dir | Select-Object -First 5 Name
}
