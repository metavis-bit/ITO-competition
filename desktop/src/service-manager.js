// Spawns and supervises the three child services (backend, digital-human, frontend)
// and reports status upstream so the splash window can render progress.

const { spawn } = require('node:child_process');
const { EventEmitter } = require('node:events');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');

class ServiceManager extends EventEmitter {
  constructor({ paths, env }) {
    super();
    this.paths = paths;
    this.env = env;
    this.children = [];
    this.isStopping = false;
    this.isStopped = false;
  }

  _openLog(name) {
    const file = path.join(this.paths.logsDir, `${name}.log`);
    return fs.createWriteStream(file, { flags: 'a' });
  }

  _status(kind, service, message, extra = {}) {
    this.emit('status', { kind, service, message, ts: Date.now(), ...extra });
  }

  _spawn({ name, command, args, cwd, extraEnv = {} }) {
    const logStream = this._openLog(name);
    logStream.write(`\n[${new Date().toISOString()}] Starting ${name}: ${command} ${args.join(' ')}\n`);

    const fullEnv = {
      ...process.env,
      ...this.env,
      ...extraEnv,
    };

    const child = spawn(command, args, {
      cwd,
      env: fullEnv,
      windowsHide: true,
      stdio: ['ignore', 'pipe', 'pipe'],
    });

    child.stdout.on('data', (chunk) => logStream.write(chunk));
    child.stderr.on('data', (chunk) => logStream.write(chunk));

    child.on('exit', (code, signal) => {
      logStream.write(`\n[${new Date().toISOString()}] ${name} exited code=${code} signal=${signal}\n`);
      logStream.end();
      if (!this.isStopping) {
        this._status('error', name, `服务异常退出 (code=${code})`);
      }
    });

    this.children.push({ name, child });
    return child;
  }

  async start() {
    this._ensureLayout();

    this._status('progress', 'backend', '正在启动知识引擎服务...');
    this._spawn({
      name: 'backend',
      command: this.paths.pythonExe,
      args: ['-m', 'uvicorn', 'src.rag.bootstrap:create_app', '--factory',
             '--host', '127.0.0.1', '--port', '9527'],
      cwd: this.paths.backendDir,
      extraEnv: {
        PYTHONPATH: this._buildPythonPath(this.paths.backendDir),
      },
    });

    this._status('progress', 'digital-human', '正在启动数字人服务...');
    this._spawn({
      name: 'digital-human',
      command: this.paths.pythonExe,
      args: ['-m', 'uvicorn', 'avatar_service.main:create_app', '--factory',
             '--host', '127.0.0.1', '--port', '8000'],
      cwd: this.paths.digitalHumanDir,
      extraEnv: {
        PYTHONPATH: this._buildPythonPath(this.paths.digitalHumanDir),
      },
    });

    this._status('progress', 'frontend', '正在启动前端界面...');
    // Next.js standalone server.js is a plain Node entrypoint
    this._spawn({
      name: 'frontend',
      command: process.execPath, // Electron's bundled Node runtime
      args: [this.paths.frontendEntry],
      cwd: this.paths.frontendDir,
      extraEnv: {
        ELECTRON_RUN_AS_NODE: '1',
        PORT: '3000',
        HOSTNAME: '127.0.0.1',
      },
    });

    // Poll backend model-download status file so the splash can show progress.
    this._pollModelStatus();
  }

  _ensureLayout() {
    // Make userData dirs visible to the backend via working directory.
    // The backend expects ./rag_store, ./models, ./knowledge_base relative to cwd.
    // We symlink/junction userData versions into the packaged backend dir if it's
    // read-only (inside resources/). Fallback: change cwd to userDataRoot.
    const targets = [
      { name: 'rag_store', src: this.paths.ragStoreDir },
      { name: 'models', src: this.paths.modelsDir },
      { name: 'knowledge_base', src: this.paths.knowledgeBaseDir },
    ];
    for (const { name, src } of targets) {
      fs.mkdirSync(src, { recursive: true });
      const linkPath = path.join(this.paths.backendDir, name);
      try {
        const stat = fs.lstatSync(linkPath, { throwIfNoEntry: false });
        if (!stat) {
          fs.symlinkSync(src, linkPath, 'junction');
        } else if (stat.isSymbolicLink()) {
          // Already linked; leave as-is. If pointing at a stale target, re-link.
          const current = fs.readlinkSync(linkPath);
          if (path.resolve(current) !== path.resolve(src)) {
            fs.rmSync(linkPath, { force: true });
            fs.symlinkSync(src, linkPath, 'junction');
          }
        }
      } catch (err) {
        // Junctions fail if backend dir is on a different volume; fall back to copy bootstrap.
        console.warn(`[service-manager] could not link ${linkPath} -> ${src}:`, err.message);
      }
    }
  }

  _buildPythonPath(serviceDir) {
    const sitePackages = path.join(this.paths.pythonRuntimeDir, 'Lib', 'site-packages');
    return [serviceDir, sitePackages].filter(Boolean).join(path.delimiter);
  }

  _pollModelStatus() {
    const statusFile = path.join(this.paths.ragStoreDir, 'model_download.status');
    const interval = setInterval(() => {
      if (this.isStopping) {
        clearInterval(interval);
        return;
      }
      fs.readFile(statusFile, 'utf8', (err, data) => {
        if (err) return;
        try {
          const payload = JSON.parse(data);
          if (payload.stage === 'downloading') {
            this._status('progress', 'backend',
              `首次启动，正在下载模型 ${payload.repo_id || ''}...`, payload);
          } else if (payload.stage === 'ready') {
            this._status('progress', 'backend', '模型就绪，正在加载...');
            clearInterval(interval);
          }
        } catch {}
      });
    }, 1500);
  }

  waitForFrontend(url, timeoutMs = 60_000) {
    const deadline = Date.now() + timeoutMs;
    return new Promise((resolve, reject) => {
      const attempt = () => {
        if (Date.now() > deadline) {
          reject(new Error(`前端服务 ${url} 在 ${timeoutMs / 1000}s 内未就绪`));
          return;
        }
        const req = http.get(url, (res) => {
          res.resume();
          if (res.statusCode && res.statusCode < 500) {
            this._status('ready', 'frontend', '界面就绪');
            resolve();
          } else {
            setTimeout(attempt, 800);
          }
        });
        req.on('error', () => setTimeout(attempt, 800));
        req.setTimeout(2000, () => req.destroy());
      };
      attempt();
    });
  }

  async stop() {
    if (this.isStopping) return;
    this.isStopping = true;

    await Promise.all(this.children.map(({ name, child }) => this._killChild(name, child)));
    this.children = [];
    this.isStopped = true;
  }

  _killChild(name, child) {
    return new Promise((resolve) => {
      if (!child || child.exitCode !== null) {
        resolve();
        return;
      }
      const done = () => resolve();
      child.once('exit', done);

      try {
        // Use taskkill on Windows for reliable tree kill (kills uvicorn child workers too).
        if (process.platform === 'win32') {
          spawn('taskkill', ['/pid', String(child.pid), '/t', '/f'], { windowsHide: true })
            .on('close', () => {});
        } else {
          child.kill('SIGTERM');
        }
      } catch (err) {
        console.warn(`[service-manager] kill ${name} failed:`, err.message);
      }

      setTimeout(() => {
        if (child.exitCode === null) {
          try { child.kill('SIGKILL'); } catch {}
          resolve();
        }
      }, 5000);
    });
  }
}

module.exports = { ServiceManager };
