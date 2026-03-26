@echo off
chcp 65001 >nul
echo ============================================
echo   智绘生物 RAG 后端启动脚本
echo ============================================
echo.

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python 未安装，请先安装 Python 3.10+
    pause
    exit /b 1
)

REM Check if deps installed
python -c "import fastapi" >nul 2>&1
if errorlevel 1 (
    echo [INFO] 正在安装 Python 依赖...
    pip install -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] 依赖安装失败
        pause
        exit /b 1
    )
)

REM Check models
if not exist "models\bge-m3" (
    echo [WARN] BGE-M3 模型未下载，正在下载...
    echo       需要约 2GB，请耐心等待...
    set HF_ENDPOINT=https://hf-mirror.com
    pip install huggingface_hub >nul 2>&1
    huggingface-cli download BAAI/bge-m3 --local-dir models/bge-m3
    if errorlevel 1 (
        echo [ERROR] 模型下载失败，请检查网络
        echo         手动下载: huggingface-cli download BAAI/bge-m3 --local-dir models/bge-m3
        pause
        exit /b 1
    )
)

REM Check for OPENAI_API_KEY
if "%OPENAI_API_KEY%"=="" (
    echo [WARN] OPENAI_API_KEY 未设置
    echo        请设置千问 API Key:
    echo        set OPENAI_API_KEY=sk-your-key
    echo        set OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
    echo.
)

echo [INFO] 启动 RAG 后端服务 (端口 9527)...
echo        按 Ctrl+C 停止
echo.
python -m uvicorn src.rag.bootstrap:create_app --factory --host 0.0.0.0 --port 9527 --reload
pause
