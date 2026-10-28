@echo off
title 文献镜像 ScholarMirror - 启动
chcp 65001 >nul
cd /d "%~dp0"

REM ---------------------------------------------------------------
REM 解释器选择：WorkBuddy 自带环境 → D:\python → PATH 上的 python
REM ---------------------------------------------------------------
set "PYTHON="
set "PYEXE=%USERPROFILE%\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
if exist "%PYEXE%" set "PYTHON=%PYEXE%"

if not defined PYTHON if exist "D:\python\python.exe" set "PYTHON=D:\python\python.exe"

if not defined PYTHON (
    for %%P in (python.exe) do (
        if not defined PYTHON if exist "%%~$PATH:P" set "PYTHON=%%~$PATH:P"
    )
)

if not defined PYTHON (
    echo [错误] 没有找到 Python。请先安装 Python 3.10 以上版本。
    pause
    exit /b 1
)

echo 使用解释器: %PYTHON%
"%PYTHON%" -c "import streamlit, numpy, plotly" >nul 2>&1
if errorlevel 1 (
    echo 正在安装依赖，第一次运行需要几分钟...
    "%PYTHON%" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [错误] 依赖安装失败，请手动执行: pip install -r requirements.txt
        pause
        exit /b 1
    )
)

echo.
echo   文献镜像 ScholarMirror 正在启动...
echo   浏览器会自动打开 http://localhost:8601
echo   关闭这个窗口即可停止服务。
echo.
"%PYTHON%" -m streamlit run app.py --server.port 8601 --server.headless false
pause
