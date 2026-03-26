# 智绘生物（GitHub 精简部署版）

本仓库是可直接本地部署的精简发布包，仅保留运行所需代码与配置。

## 1. 包含内容

```text
backend/         # FastAPI + RAG + 课件生成后端
frontend/        # Next.js 前端
digital-human/   # 数字人服务（可选）
LICENSE          # 开源许可证文本（含借鉴代码的许可信息）
版权与开源借鉴声明.md
```

## 2. 运行前准备

- Node.js >= 20.9
- pnpm >= 10
- Python >= 3.10（后端）
- Docker（用于 Milvus）

## 3. 快速启动

### 3.1 启动 Milvus（终端 1）

```bash
cd backend
docker compose up -d
```

### 3.2 启动后端（终端 1）

```bash
cd backend
pip install -r requirements.txt

# 必填：大模型 API
set OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
set OPENAI_API_KEY=sk-你的key

# 首次建议下载模型
huggingface-cli download BAAI/bge-m3 --local-dir models/bge-m3
huggingface-cli download BAAI/bge-reranker-large --local-dir models/bge-reranker-large

python -m uvicorn src.rag.bootstrap:create_app --factory --host 0.0.0.0 --port 9527 --reload
```

### 3.3 启动前端（终端 2）

```bash
cd frontend
pnpm install
```

创建 `frontend/.env.local`：

```env
BACKEND_ENABLED=true
BACKEND_URL=http://localhost:9527

AVATAR_SERVICE_ENABLED=false
AVATAR_SERVICE_URL=http://localhost:8000
```

运行：

```bash
pnpm dev
```

访问：http://localhost:3000

### 3.4 启动数字人（可选，终端 3）

```bash
cd digital-human
pip install -e .
uvicorn avatar_service.main:app --port 8000 --reload
```

## 4. 知识库说明

- 默认知识库目录：`backend/knowledge_base/`
- 后端首次启动会自动检测并尝试入库。
- 也可通过前端上传 PDF/Word/PPT/图片/视频进行会话级入库。

## 5. 版权与开源借鉴

- 本项目借鉴 OpenMaic 开源项目，并在其基础上进行二次开发与教学场景适配。
- 借鉴部分遵循其原始开源许可证约束（以许可证文件和上游项目声明为准）。
- 详细法律与使用声明见：[版权与开源借鉴声明.md](./版权与开源借鉴声明.md)
