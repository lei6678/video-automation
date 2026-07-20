@echo off
chcp 65001 >nul 2>&1
title 视频自动化工作台

cd /d "%~dp0"

:: ★ 首次使用检测：没有 .env = 朋友版，引导配置
if not exist ".env" (
    echo ============================================
    echo   欢迎使用视频自动化工作台！
    echo   检测到您尚未配置 API 密钥
    echo ============================================
    echo.
    echo 即将为您打开 .env.example 模板文件...
    echo 请用记事本填入您自己的 API 密钥，然后：
    echo   文件 → 另存为 → 文件名改为 .env → 保存
    echo.
    echo 保存后，再次双击本 bat 即可启动。
    echo ============================================
    echo.
    start notepad ".env.example"
    pause
    exit /b 0
)

echo ============================================
echo   视频自动化工作台
echo   关闭本窗口即停止服务
echo ============================================
echo.
echo Starting...
echo.

VideoWorkstation.exe
pause
