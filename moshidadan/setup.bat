@echo off
chcp 65001 >nul 2>&1
title 产地快打 - 一键安装与打包
echo.
echo   ╔══════════════════════════════════════╗
echo   ║     产地快打 — 一键安装与打包       ║
echo   ║     本脚本将自动安装所需环境         ║
echo   ╚══════════════════════════════════════╝
echo.

:: ============================================================
::  Step 1: 检查/安装 Python
:: ============================================================
echo [1/4] 检查 Python 环境...
echo.

where python >nul 2>&1
if %errorlevel% equ 0 (
    python --version
    echo   ✅ Python 已安装
    goto :check_pip
)

echo   ❌ 未检测到 Python
echo.
echo   正在通过 winget 自动安装 Python 3.12...
echo   （如弹出用户账户控制窗口，请点击"是"）
echo.

:: 检查 winget 是否可用
where winget >nul 2>&1
if %errorlevel% neq 0 (
    echo   ❌ winget 不可用（系统版本过旧）
    echo.
    echo   ╔══════════════════════════════════════════╗
    echo   ║  请手动安装 Python 3.12+:               ║
    echo   ║  https://www.python.org/downloads/      ║
    echo   ║  安装时务必勾选 "Add Python to PATH"    ║
    echo   ║  安装完成后重新运行本脚本               ║
    echo   ╚══════════════════════════════════════════╝
    echo.
    start https://www.python.org/downloads/
    pause
    exit /b 1
)

winget install Python.Python.3.12 --accept-source-agreements --accept-package-agreements
if %errorlevel% neq 0 (
    echo.
    echo   ❌ 自动安装失败，请手动安装:
    echo   https://www.python.org/downloads/
    echo   安装时务必勾选 "Add Python to PATH"
    pause
    start https://www.python.org/downloads/
    exit /b 1
)

echo   ✅ Python 3.12 安装完成

:: 刷新 PATH（使用新安装的 Python）
echo   正在刷新环境变量...
call :refresh_env
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo   ⚠️  Python 已安装但 PATH 未更新
    echo   请重启电脑后重新运行本脚本
    echo   或者手动将 Python 添加到系统 PATH
    pause
    exit /b 1
)

python --version
echo   ✅ Python 可用

:check_pip
:: ============================================================
::  Step 2: 升级 pip
:: ============================================================
echo.
echo [2/4] 升级 pip...
python -m pip install --upgrade pip --quiet
if %errorlevel% neq 0 (
    echo   ⚠️  pip 升级失败（不影响后续），继续...
) else (
    echo   ✅ pip 已是最新
)

:: ============================================================
::  Step 3: 安装打包工具
:: ============================================================
echo.
echo [3/4] 安装打包工具 (PyInstaller + Pillow)...
echo   这可能需要 1-2 分钟，请稍候...
echo.

python -m pip install pyinstaller Pillow
if %errorlevel% neq 0 (
    echo.
    echo   ❌ 安装失败，尝试使用国内镜像...
    python -m pip install pyinstaller Pillow -i https://mirrors.aliyun.com/pypi/simple/
    if %errorlevel% neq 0 (
        echo.
        echo   ❌ 仍然失败，请检查网络连接后重试
        pause
        exit /b 1
    )
)
echo   ✅ 打包工具安装完成

:: ============================================================
::  Step 4: 执行打包
:: ============================================================
echo.
echo [4/4] 开始打包...
echo.
for /f "usebackq delims=" %%V in (`python -c "import json;print(json.load(open('app_config.json',encoding='utf-8'))['version'])"`) do set "APP_VERSION=%%V"
if "%APP_VERSION%"=="" set "APP_VERSION=v1.0.0"
set "EXE_NAME=产地快打_%APP_VERSION%"
echo   ╔══════════════════════════════════════════╗
echo   ║  正在生成 %EXE_NAME%.exe（约 2-5 分钟）  ║
echo   ╚══════════════════════════════════════════╝
echo.

call build.bat
set "EXE_FILE="
for %%F in ("dist\*.exe") do set "EXE_FILE=%%~nxF"
if defined EXE_FILE (
    echo.
    echo   ╔══════════════════════════════════════════╗
    echo   ║  🎉 全部完成！                          ║
    echo   ║  📁 dist\%EXE_FILE%                     ║
    echo   ║  建议: 重启电脑使 PATH 永久生效         ║
    echo   ╚══════════════════════════════════════════╝
    echo.
) else (
    echo.
    echo   ╔══════════════════════════════════════════╗
    echo   ║  ⚠️  打包未成功                          ║
    echo   ║  请检查上方错误信息                      ║
    echo   ╚══════════════════════════════════════════╝
    echo.
)

pause
exit /b 0

:: ============================================================
:: 辅助函数：刷新环境变量 PATH
:: ============================================================
:refresh_env
    setlocal EnableDelayedExpansion
    for /f "tokens=2* delims= " %%a in ('reg query "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment" /v PATH 2^>nul') do set "syspath=%%b"
    for /f "tokens=2* delims= " %%a in ('reg query "HKCU\Environment" /v PATH 2^>nul') do set "userpath=%%b"
    endlocal & set "PATH=%syspath%;%userpath%;%PATH%"
    goto :eof
