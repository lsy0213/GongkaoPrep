@echo off
chcp 65001 >nul
rem 从源码启动（桌面窗口）。打包好的版本直接双击 dist\GongkaoPrep.exe 即可。
cd /d "%~dp0"
conda run -n gongkao-prep pythonw main.py
if errorlevel 1 (
  echo.
  echo 启动失败。请先创建环境：conda create -n gongkao-prep python=3.11 -y
  echo 再安装依赖：conda run -n gongkao-prep pip install -r requirements.txt
  pause
)
