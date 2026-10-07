@echo off
chcp 65001 >nul
rem 打包 上岸备考：dist\GongkaoPrep\ 目录版（启动快、不易被误报）
rem   装了 Inno Setup 6 时再生成安装包 installer\Output\GongkaoPrep-版本-setup.exe，否则打成 zip
rem 需要先创建 conda 环境：conda create -n gongkao-prep python=3.11 -y
rem 然后安装依赖：conda run -n gongkao-prep pip install -r requirements.txt -r requirements-dev.txt

cd /d "%~dp0"

if not exist assets\icon.ico (
    echo [1/4] 生成图标...
    conda run -n gongkao-prep python tools\make_icon.py || goto :error
)

echo [2/4] 检查与测试...
conda run --no-capture-output -n gongkao-prep python -m ruff check . || goto :error
conda run --no-capture-output -n gongkao-prep python tools\check_frontend.py || goto :error
conda run --no-capture-output -n gongkao-prep python -m pytest -q || goto :error

for /f "tokens=2 delims==" %%v in ('findstr /r /c:"^VERSION = " gongkao\__init__.py') do set VER=%%~v
set VER=%VER: =%
set VER=%VER:"=%
echo 版本 %VER%

echo [3/4] 开始打包，大约需要 1-2 分钟...
conda run --no-capture-output -n gongkao-prep python -m PyInstaller --noconfirm --clean GongkaoPrep.spec || goto :error
conda run --no-capture-output -n gongkao-prep python tools\smoke_exe.py || goto :error

echo [4/4] 生成安装包...
set ISCC=
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set ISCC="%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set ISCC="%ProgramFiles%\Inno Setup 6\ISCC.exe"
if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set ISCC="%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if defined ISCC (
    %ISCC% /Q /DAppVersion=%VER% installer\GongkaoPrep.iss || goto :error
    echo 安装包：%~dp0installer\Output\GongkaoPrep-%VER%-setup.exe
) else (
    echo 没有安装 Inno Setup 6，改为打成 zip（装上 Inno Setup 后重新运行可生成安装包）
    powershell -NoProfile -Command "Compress-Archive -Path 'dist\GongkaoPrep\*' -DestinationPath 'dist\GongkaoPrep-%VER%.zip' -Force" || goto :error
    echo 压缩包：%~dp0dist\GongkaoPrep-%VER%.zip
)

echo.
echo 打包完成：%~dp0dist\GongkaoPrep\GongkaoPrep.exe
pause
exit /b 0

:error
echo.
echo 打包失败，请查看上面的错误信息。
pause
exit /b 1
