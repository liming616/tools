@echo off
chcp 65001 >nul 2>&1
title 产地快打 - 启动
echo ========================================
echo   产地快打 - 启动 (build.bat)
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

python main.py
pause
