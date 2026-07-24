@echo off
chcp 65001 >nul 2>&1
title Video Automation Server

cd /d "D:\VideoWorkstation_Deploy\backend"

echo ============================================
echo   Video Automation Server
echo   (Keep this window open, minimize it)
echo ============================================
echo.
echo Starting server...
echo.

python main.py
pause
