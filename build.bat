@echo off
chcp 65001 >nul
rem 打包 上岸备考 为单个 exe，输出到 dist\GongkaoPrep.exe
rem 需要先创建 conda 环境：conda create -n gongkao-prep python=3.11 -y
rem 然后安装依赖：conda run -n gongkao-prep pip install -r requirements.txt

cd /d "%~dp0"

if not exist assets\icon.ico (
    echo [1/2] 生成图标...
    conda run -n gongkao-prep python tools\make_icon.py || goto :error
)

echo [2/2] 开始打包，大约需要 1 分钟...
conda run --no-capture-output -n gongkao-prep python -m PyInstaller ^
    --noconfirm --clean --onefile --windowed ^
    --name GongkaoPrep ^
    --icon assets\icon.ico ^
    --add-data "web;web" ^
    --add-data "content;content" ^
    --add-data "assets\icon.ico;assets" ^
    --collect-all pymupdf ^
    --collect-data docx ^
    --collect-all rapidocr_onnxruntime ^
    --collect-all onnxruntime ^
    main.py || goto :error

echo.
echo 打包完成：%~dp0dist\GongkaoPrep.exe
pause
exit /b 0

:error
echo.
echo 打包失败，请查看上面的错误信息。
pause
exit /b 1
