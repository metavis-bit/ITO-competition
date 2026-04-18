# 智绘生物 — Windows 桌面安装包

将 `backend` / `digital-human` / `frontend` 三个服务打包为一个独立的 Windows 桌面应用，并生成 NSIS 安装程序。

```
ITO智绘生物-Setup-1.0.0.exe   (≈ 1.5 GB)
└─ 安装后
   智绘生物.exe               (Electron 启动器)
   resources/
     python-runtime/          (Python 3.11 embeddable + 已安装依赖)
     backend/                 (后端源码)
     digital-human/           (数字人服务源码)
     frontend/                (Next.js standalone 构建)
```

用户首次启动时，应用会自动从 HuggingFace 镜像下载 `bge-m3` 和 `bge-reranker-large` 模型（约 2.3 GB），保存在 `%APPDATA%\智绘生物\ito-data\models\`。

## 运行环境要求

### 构建机（开发者）
- Windows 10/11 x64
- Node.js ≥ 20.9
- pnpm ≥ 10（或 `corepack enable` + `corepack prepare pnpm@10.28.0 --activate`）
- **已安装**的 Python（任何 3.10+，构建阶段仅用于调用 pip；最终产物不依赖它）
- 约 20 GB 可用磁盘空间（下载 wheels + 构建产物）
- 稳定的互联网连接

### 目标机器（用户）
- Windows 10/11 x64
- ≥ 8 GB RAM（推荐 16 GB）
- ≥ 10 GB 可用磁盘空间
- 首次启动时需联网下载模型；之后可离线运行

## 构建流程

```powershell
cd desktop

# 1. 安装 Electron / electron-builder
npm install

# 2. 准备 Python 运行时（下载 embeddable Python 3.11，安装全部依赖）
#    ≈ 15-25 分钟（取决于网速，torch/transformers/FlagEmbedding 体积较大）
npm run prepare:runtime

# 3. 构建前端并拷贝到 resources/frontend
#    ≈ 3-5 分钟
npm run prepare:frontend

# 4. 生成 NSIS 安装程序
npm run dist
# 产物: desktop/dist/智绘生物-Setup-1.0.0.exe
```

> 如果要快速验证不生成安装包，可用 `npm run pack` 产出未压缩的 `dist/win-unpacked/` 目录直接运行。

## 开发时直接运行（不经过打包）

前提：已完成 `prepare:runtime` 和 `prepare:frontend`，此时 `desktop/resources/` 已经就绪。

```powershell
cd desktop
npm start
```

Electron 会启动 splash 窗口 → 拉起三个子服务 → 加载 http://127.0.0.1:3000。日志位于 `%APPDATA%\智绘生物\ito-data\logs\`。

## 关键改动点回顾

| 文件 | 改动 | 原因 |
|---|---|---|
| `backend/config.yaml` | `uri` 改为 `./rag_store/milvus_lite.db`；`device: cuda` → `auto`；`use_fp16: false` | 桌面端无 Docker / 无 GPU 默认值 |
| `backend/src/rag/config.py` | 新增 `_apply_device_auto()`，`device: auto` 运行时自动探测 CUDA | 同时兼容 GPU 用户 |
| `backend/src/rag/utils/model_downloader.py` | 新增：启动时检查并下载 bge-m3/bge-reranker-large | 首次运行体验 |
| `backend/src/rag/bootstrap.py` | 启动前调用 `ensure_models(cfg)` | 确保 RAGEngine 初始化前模型就位 |
| `backend/requirements.txt` | 添加 `milvus-lite`、`huggingface-hub` | 运行时依赖 |

原有 `docker-compose.yml` 保留但**不再使用**，仅供开发者回退到 Milvus Standalone 模式时参考。

## 运行时数据布局

```
%APPDATA%\智绘生物\ito-data\
  logs\                    # 三个服务的 stdout/stderr
    backend.log
    digital-human.log
    frontend.log
  rag_store\
    milvus_lite.db         # Milvus Lite 向量库
    cache\                 # Embedding 缓存
    .kb_fingerprint        # 知识库增量 ingest 指纹
    model_download.status  # splash 读取的进度文件
  models\
    bge-m3\                # 首次启动下载
    bge-reranker-large\
  knowledge_base\          # 用户可投放文档
  hf_cache\                # HuggingFace 缓存
```

Electron 主进程会把 `backend/rag_store`、`backend/models`、`backend/knowledge_base` 以 Windows junction 的方式指向以上可写目录，避免在安装目录写文件。

## 常见问题

**Q: 构建时 pnpm 报 `ERR_PNPM_PEER_DEP_ISSUES`**
A: `pnpm install --frozen-lockfile` 时遇到 peer 警告不影响构建。如果是 error，临时用 `pnpm install --strict-peer-dependencies=false` 即可。

**Q: 安装后启动失败 "服务异常退出"**
A: 打开 `%APPDATA%\智绘生物\ito-data\logs\backend.log` 查看。常见原因：杀毒软件拦截 python.exe；端口 3000/9527/8000 被占用。

**Q: 想改成捆绑模型**
A: 在 `desktop/scripts/prepare-python-runtime.js` 末尾追加 snapshot_download 调用，把模型下载到 `desktop/resources/backend/models/`；然后安装包体积会从 ≈ 1.5 GB 涨到 ≈ 4 GB。

**Q: Qwen API Key 如何更换？**
A: 编辑 [src/config.js](src/config.js) 中的 `QWEN_API_KEY` 常量，以及 `scripts/prepare-frontend.js` 的同名常量，重新构建。
