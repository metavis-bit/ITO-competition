// Prepares a self-contained Python 3.11 runtime under resources/python-runtime.
//
// Strategy:
//   1. Download the Windows "embeddable" Python 3.11 zip from python.org
//   2. Extract it into resources/python-runtime/
//   3. Un-comment `import site` in python311._pth so packages under Lib/site-packages load
//   4. Bootstrap pip via get-pip.py
//   5. pip install -r backend/requirements.txt into Lib/site-packages (CPU-only torch)
//   6. pip install -e digital-human (or just install its deps)
//   7. Copy backend & digital-human sources into resources/
//
// Run with: node desktop/scripts/prepare-python-runtime.js

const fs = require('node:fs');
const path = require('node:path');
const https = require('node:https');
const { spawnSync } = require('node:child_process');

const PY_VERSION = '3.11.9';
const PY_ARCH = 'amd64';
const PY_URL = `https://www.python.org/ftp/python/${PY_VERSION}/python-${PY_VERSION}-embed-${PY_ARCH}.zip`;
const GET_PIP_URL = 'https://bootstrap.pypa.io/get-pip.py';

const ROOT = path.resolve(__dirname, '..', '..');
const DESKTOP_DIR = path.resolve(__dirname, '..');
const RESOURCES_DIR = path.join(DESKTOP_DIR, 'resources');
const RUNTIME_DIR = path.join(RESOURCES_DIR, 'python-runtime');
const SITE_PACKAGES = path.join(RUNTIME_DIR, 'Lib', 'site-packages');
const TMP_DIR = path.join(DESKTOP_DIR, '.tmp');

const BACKEND_SRC = path.join(ROOT, 'backend');
const DIGITAL_HUMAN_SRC = path.join(ROOT, 'digital-human');
const BACKEND_DST = path.join(RESOURCES_DIR, 'backend');
const DIGITAL_HUMAN_DST = path.join(RESOURCES_DIR, 'digital-human');

function log(msg) {
  console.log(`\n\x1b[36m[prepare-python]\x1b[0m ${msg}`);
}

function ensureDir(p) {
  fs.mkdirSync(p, { recursive: true });
}

function download(url, dest) {
  return new Promise((resolve, reject) => {
    log(`downloading ${url}`);
    const file = fs.createWriteStream(dest);
    const followGet = (currentUrl) => {
      https.get(currentUrl, (res) => {
        if (res.statusCode && res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
          res.resume();
          followGet(res.headers.location);
          return;
        }
        if (res.statusCode !== 200) {
          reject(new Error(`HTTP ${res.statusCode} for ${currentUrl}`));
          return;
        }
        res.pipe(file);
        file.on('finish', () => file.close(resolve));
      }).on('error', reject);
    };
    followGet(url);
  });
}

function unzip(zipPath, destDir) {
  log(`extracting ${path.basename(zipPath)} -> ${destDir}`);
  const result = spawnSync('powershell.exe', [
    '-NoProfile',
    '-Command',
    `Expand-Archive -Force -Path '${zipPath}' -DestinationPath '${destDir}'`,
  ], { stdio: 'inherit' });
  if (result.status !== 0) throw new Error('Expand-Archive failed');
}

function run(cmd, args, opts = {}) {
  log(`$ ${cmd} ${args.join(' ')}`);
  const result = spawnSync(cmd, args, {
    stdio: 'inherit',
    shell: false,
    ...opts,
  });
  if (result.status !== 0) {
    throw new Error(`Command failed (${result.status}): ${cmd} ${args.join(' ')}`);
  }
}

function enableSiteInPth(runtimeDir) {
  // Embeddable Python ships a pythonXX._pth that disables site-packages by default.
  const pthFiles = fs.readdirSync(runtimeDir).filter((f) => /^python\d+\._pth$/.test(f));
  for (const name of pthFiles) {
    const p = path.join(runtimeDir, name);
    let content = fs.readFileSync(p, 'utf8');
    if (!/^import site/m.test(content)) {
      content = content.replace(/^#\s*import site/m, 'import site');
      if (!/^import site/m.test(content)) content += '\nimport site\n';
      fs.writeFileSync(p, content, 'utf8');
      log(`enabled site in ${name}`);
    }
    // Also make Lib/site-packages discoverable.
    if (!/Lib\\site-packages/.test(content) && !/Lib\/site-packages/.test(content)) {
      fs.appendFileSync(p, '\nLib\\site-packages\n', 'utf8');
    }
  }
}

function copyDir(src, dst, { exclude = [] } = {}) {
  log(`copy ${src} -> ${dst}`);
  fs.rmSync(dst, { recursive: true, force: true });
  ensureDir(dst);
  function walk(from, to) {
    for (const entry of fs.readdirSync(from, { withFileTypes: true })) {
      if (exclude.includes(entry.name)) continue;
      const s = path.join(from, entry.name);
      const d = path.join(to, entry.name);
      if (entry.isDirectory()) {
        ensureDir(d);
        walk(s, d);
      } else if (entry.isFile()) {
        fs.copyFileSync(s, d);
      }
    }
  }
  walk(src, dst);
}

async function main() {
  ensureDir(TMP_DIR);
  ensureDir(RESOURCES_DIR);

  // --- Step 1: download + extract embeddable Python ---
  if (!fs.existsSync(path.join(RUNTIME_DIR, 'python.exe'))) {
    const zipPath = path.join(TMP_DIR, `python-${PY_VERSION}-embed.zip`);
    if (!fs.existsSync(zipPath)) await download(PY_URL, zipPath);
    fs.rmSync(RUNTIME_DIR, { recursive: true, force: true });
    ensureDir(RUNTIME_DIR);
    unzip(zipPath, RUNTIME_DIR);
    enableSiteInPth(RUNTIME_DIR);
  } else {
    log('python-runtime already present, skipping download');
    enableSiteInPth(RUNTIME_DIR);
  }

  const pythonExe = path.join(RUNTIME_DIR, 'python.exe');

  // --- Step 2: bootstrap pip ---
  ensureDir(SITE_PACKAGES);
  const pipMarker = path.join(SITE_PACKAGES, 'pip');
  if (!fs.existsSync(pipMarker)) {
    const getPipPath = path.join(TMP_DIR, 'get-pip.py');
    if (!fs.existsSync(getPipPath)) await download(GET_PIP_URL, getPipPath);
    run(pythonExe, [getPipPath, '--no-warn-script-location']);
  } else {
    log('pip already bootstrapped');
  }

  // --- Step 3: install backend deps (CPU torch) ---
  // Priority: CPU torch from pytorch index to avoid 2.5 GB CUDA wheels.
  log('installing CPU-only torch');
  run(pythonExe, [
    '-m', 'pip', 'install',
    '--no-warn-script-location',
    '--index-url', 'https://download.pytorch.org/whl/cpu',
    'torch==2.4.1',
  ]);

  log('installing backend requirements');
  run(pythonExe, [
    '-m', 'pip', 'install',
    '--no-warn-script-location',
    '-r', path.join(BACKEND_SRC, 'requirements.txt'),
  ]);

  // --- Step 4: install digital-human (editable not viable in packaged app; install deps only) ---
  log('installing digital-human');
  run(pythonExe, [
    '-m', 'pip', 'install',
    '--no-warn-script-location',
    BACKEND_SRC.replace(/\\/g, '/') === DIGITAL_HUMAN_SRC.replace(/\\/g, '/') ? '' : DIGITAL_HUMAN_SRC,
  ].filter(Boolean));

  // --- Step 5: copy sources into resources/ ---
  copyDir(BACKEND_SRC, BACKEND_DST, {
    exclude: ['__pycache__', '.pytest_cache', 'rag_store', 'knowledge_base', 'models', 'outputs', 'docker-compose.yml'],
  });
  copyDir(DIGITAL_HUMAN_SRC, DIGITAL_HUMAN_DST, {
    exclude: ['__pycache__', '.pytest_cache', 'avatar_service.egg-info'],
  });

  // Write a sentinel empty .gitkeep inside models/knowledge_base dirs of the packaged backend.
  // At runtime these are replaced with junctions into userData.
  ensureDir(path.join(BACKEND_DST, 'models'));
  ensureDir(path.join(BACKEND_DST, 'knowledge_base'));
  ensureDir(path.join(BACKEND_DST, 'rag_store'));

  log('done');
}

main().catch((err) => {
  console.error('\n\x1b[31m[prepare-python] failed:\x1b[0m', err);
  process.exit(1);
});
