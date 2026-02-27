@echo off
chcp 65001 >nul
echo ╔══════════════════════════════════════════════════════════════╗
echo ║        🏦 A股金融智能体分析系统 - Chainlit 前端              ║
echo ╚══════════════════════════════════════════════════════════════╝
echo.

cd /d "%~dp0"

if not defined CONDA_DEFAULT_ENV (
    echo [错误] 未检测到 Conda 环境，请先激活 stock_project 环境
    echo.
    echo 运行命令: conda activate stock_project
    pause
    exit /b 1
)

if not "%CONDA_DEFAULT_ENV%"=="stock_project" (
    echo [警告] 当前环境: %CONDA_DEFAULT_ENV%
    echo [提示] 建议使用 stock_project 环境: conda activate stock_project
    echo.
)

echo [信息] 启动 Chainlit 服务...
echo [信息] 访问地址: http://localhost:8000
echo.

chainlit run app.py --port 8000 --host 0.0.0.0