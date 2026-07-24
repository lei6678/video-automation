@echo off
chcp 65001 >nul 2>&1
title 打包重建 — 一键完成

cd /d "%~dp0"

echo ============================================
echo   视频自动化工作台 — 打包重建
echo   同事只需要 dist\VideoWorkstation\ 文件夹
echo ============================================
echo.

echo [0/3] 检查 FFmpeg 依赖...
if not exist "bin\ffmpeg.exe" (
    echo ⚠️  未找到 bin\ffmpeg.exe，请先从 D:\ffmpeg 或其他位置复制到 bin\
    pause
    exit /b 1
)
echo ✅ FFmpeg 已就绪
echo.

echo [1/3] PyInstaller 打包...
pyinstaller VideoWorkstation.spec
if %errorlevel% neq 0 (
    echo ❌ 打包失败，请检查上方错误信息
    pause
    exit /b %errorlevel%
)
echo ✅ 打包完成
echo.

echo [2/3] 复制 BGM 文件夹...
if exist "bgm\背景音乐.mp3" (
    xcopy /E /I /Y "bgm" "dist\VideoWorkstation\bgm\" >nul 2>&1
    echo ✅ BGM 已复制
) else (
    mkdir "dist\VideoWorkstation\bgm" 2>nul
    echo ⚠️  无 BGM 文件，已创建空目录
)

echo [3/3] 复制启动文件和密钥...
if exist "backend\.env" (
    copy /Y "backend\.env" "dist\VideoWorkstation\.env" >nul 2>&1
    echo ✅ .env 密钥已复制
) else (
    echo ⚠️  未找到 backend\.env，同事需自行创建
)
:: ★ 注意：启动工作台已包含智能引导逻辑，打包后直接复制 dist 源文件而非项目根 bat
copy /Y "dist_assets\启动工作台.bat" "dist\VideoWorkstation\" >nul 2>&1
echo ✅ 启动工作台.bat 已复制
if exist "backend\.env.example" (
    copy /Y "backend\.env.example" "dist\VideoWorkstation\.env.example" >nul 2>&1
    echo ✅ .env.example 模板已复制（给朋友用）
)

echo.
echo ============================================
echo   打包重建完成！
echo   dist\VideoWorkstation\ 可以直接发给同事
echo ============================================
pause
