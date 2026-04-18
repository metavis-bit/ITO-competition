// Central configuration: resolves paths for dev vs packaged runtime
// and assembles the env block passed to every child service.

const { app } = require('electron');
const path = require('node:path');
const fs = require('node:fs');

// Hardcoded Qwen API key — requested by product: no user input needed.
const QWEN_API_KEY = 'sk-65677aded2b3454ca728cfb517ced27f';
const QWEN_BASE_URL = 'https://dashscope.aliyuncs.com/compatible-mode/v1';
const QWEN_TTS_BASE_URL = 'https://dashscope.aliyuncs.com/api/v1';

const isPackaged = app.isPackaged;

// resourcesRoot: where extraResources land at runtime.
//   packaged: <install-dir>/resources (process.resourcesPath)
//   dev:      <repo>/desktop/resources (after `npm run prepare:all`)
const resourcesRoot = isPackaged
  ? process.resourcesPath
  : path.resolve(__dirname, '..', 'resources');

// repoRoot points at the parent repo when running from source (for dev reload).
const repoRoot = path.resolve(__dirname, '..', '..');

// In dev mode we can fall back to the live repo if resources/ was not prepared.
function pickFirstExisting(candidates) {
  for (const candidate of candidates) {
    if (candidate && fs.existsSync(candidate)) return candidate;
  }
  return candidates[candidates.length - 1];
}

const pythonRuntimeDir = pickFirstExisting([
  path.join(resourcesRoot, 'python-runtime'),
]);

const backendDir = pickFirstExisting([
  path.join(resourcesRoot, 'backend'),
  path.join(repoRoot, 'backend'),
]);

const digitalHumanDir = pickFirstExisting([
  path.join(resourcesRoot, 'digital-human'),
  path.join(repoRoot, 'digital-human'),
]);

const frontendDir = pickFirstExisting([
  path.join(resourcesRoot, 'frontend'),
  path.join(repoRoot, 'frontend', '.next', 'standalone'),
]);

// Runtime-writable data lives under <userData>/ito-data (e.g. %APPDATA%/智绘生物/ito-data)
const userDataRoot = path.join(app.getPath('userData'), 'ito-data');
const logsDir = path.join(userDataRoot, 'logs');
const ragStoreDir = path.join(userDataRoot, 'rag_store');
const modelsDir = path.join(userDataRoot, 'models');
const knowledgeBaseDir = path.join(userDataRoot, 'knowledge_base');

const paths = {
  resourcesRoot,
  pythonRuntimeDir,
  pythonExe: path.join(pythonRuntimeDir, 'python.exe'),
  backendDir,
  digitalHumanDir,
  frontendDir,
  userDataRoot,
  logsDir,
  ragStoreDir,
  modelsDir,
  knowledgeBaseDir,
  frontendEntry: path.join(frontendDir, 'server.js'), // Next.js standalone entry
};

const childEnv = {
  OPENAI_API_KEY: QWEN_API_KEY,
  OPENAI_BASE_URL: QWEN_BASE_URL,
  QWEN_API_KEY,
  QWEN_BASE_URL,
  TTS_QWEN_API_KEY: QWEN_API_KEY,
  TTS_QWEN_BASE_URL: QWEN_TTS_BASE_URL,
  AVATAR_TTS_API_KEY: QWEN_API_KEY,
  AVATAR_TTS_BASE_URL: QWEN_TTS_BASE_URL,
  AVATAR_VOICE_PROFILE_MODEL: 'qwen-vl-plus-latest',
  BACKEND_ENABLED: 'true',
  BACKEND_URL: 'http://127.0.0.1:9527',
  HF_ENDPOINT: 'https://hf-mirror.com',
  PYTHONUTF8: '1',
  PYTHONIOENCODING: 'utf-8',
  // Point huggingface / transformers caches into userData so model downloads persist.
  HF_HOME: path.join(userDataRoot, 'hf_cache'),
  TRANSFORMERS_CACHE: path.join(userDataRoot, 'hf_cache'),
};

module.exports = {
  paths,
  config: {
    isPackaged,
    frontendUrl: 'http://127.0.0.1:3000',
    backendUrl: 'http://127.0.0.1:9527',
    digitalHumanUrl: 'http://127.0.0.1:8000',
    childEnv,
  },
};
