@echo off
chcp 65001 >nul 2>&1
title 产地快打 - 打包
echo ========================================
echo   产地快打 - 打包 (build.bat)
echo ========================================
echo.

:: ============================================================
::  检查 Python
:: ============================================================
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ❌ 未找到 Python
    echo.
    echo 解决方法（任选一种）:
    echo   1. 运行 setup.bat 自动安装
    echo   2. 访问 https://python.org 下载安装
    echo      ⚠️ 安装时务必勾选 "Add Python to PATH"
    echo.
    pause
    exit /b 1
)

echo Python:
python --version
echo.

:: ============================================================
::  检查 pip
:: ============================================================
python -m pip --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ❌ pip 未安装
    echo 运行: python -m ensurepip --upgrade
    pause
    exit /b 1
)

:: ============================================================
::  确保 PyInstaller 已安装
:: ============================================================
python -c "import PyInstaller" >nul 2>&1
if %errorlevel% neq 0 (
    echo ⚠️  PyInstaller 未安装，正在安装...
    python -m pip install pyinstaller Pillow
    if %errorlevel% neq 0 (
        echo ❌ 安装失败，尝试镜像...
        python -m pip install pyinstaller Pillow -i https://mirrors.aliyun.com/pypi/simple/
        if %errorlevel% neq 0 (
            echo ❌ 安装失败，请检查网络
            pause
            exit /b 1
        )
    )
)

:: ============================================================
::  生成图标（可选）
:: ============================================================
if not exist icon.ico (
    echo 正在生成图标...
    python generate_icon.py >nul 2>&1
    if %errorlevel% neq 0 (
        echo   (使用默认图标)
    ) else (
        echo   图标已生成
    )
) else (
    echo 图标已存在，跳过
)

:: ============================================================
::  清理旧文件
:: ============================================================
echo.
echo 清理旧构建...
if exist build rmdir /s /q build
if exist dist  rmdir /s /q dist

:: ============================================================
::  打包
:: ============================================================
echo.
echo 正在打包（首次约 2-5 分钟）...
echo.

if exist moshidadan.spec (
    pyinstaller moshidadan.spec --noconfirm
) else (
    if exist icon.ico (
        pyinstaller --onefile --windowed --name "产地快打" --icon=icon.ico ^
            --hidden-import tkinter --hidden-import ctypes ^
            --exclude-module matplotlib --exclude-module numpy ^
            main.py
    ) else (
        pyinstaller --onefile --windowed --name "产地快打" ^
            --hidden-import tkinter --hidden-import ctypes ^
            --exclude-module matplotlib --exclude-module numpy ^
            main.py
    )
)

:: ============================================================
::  结果
:: ============================================================
echo.
if exist "dist\产地快打.exe" (
    for %%A in ("dist\产地快打.exe") do echo ✅ 打包成功！文件大小: %%~zA 字节
    echo.
    echo 📁 dist\产地快打.exe
    echo.
    echo 使用:
    echo   1. 双击 产地快打.exe
    echo   2. 设置中填写打单软件窗口标题关键词
    echo   3. 微信中双击订单消息 → 自动识别 → 发送
    echo.
    start "" explorer /select,"dist\产地快打.exe"
) else (
    echo ❌ 打包失败
    echo.
    echo 常见原因:
    echo   · 杀毒软件拦截 → 临时关闭 Windows Defender 重试
    echo   · Python 版本过旧 → 需要 Python 3.10+
    echo   · 磁盘空间不足 → 至少需要 500MB 空闲空间
    echo.
    echo 手动打包命令:
    echo   pyinstaller --onefile --windowed --name "产地快打" main.py
    echo.
)
pause
