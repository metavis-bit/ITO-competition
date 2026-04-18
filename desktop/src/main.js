// Electron main process for 智绘生物 (ITO Desktop).
// - Spawns the three Python/Node child services using the bundled runtime
// - Shows a splash window while services come up and models are downloaded
// - Loads the Next.js frontend when it's reachable
// - Gracefully kills children on quit

const { app, BrowserWindow, ipcMain, dialog, shell } = require('electron');
const path = require('node:path');
const fs = require('node:fs');

const { config, paths } = require('./config');
const { ServiceManager } = require('./service-manager');

let splashWindow = null;
let mainWindow = null;
const serviceManager = new ServiceManager({
  paths,
  env: config.childEnv,
});

function createSplashWindow() {
  splashWindow = new BrowserWindow({
    width: 520,
    height: 360,
    frame: false,
    resizable: false,
    alwaysOnTop: true,
    show: false,
    backgroundColor: '#0f172a',
    webPreferences: {
      preload: path.join(__dirname, 'splash-preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  splashWindow.loadFile(path.join(__dirname, 'splash.html'));
  splashWindow.once('ready-to-show', () => splashWindow.show());
  splashWindow.on('closed', () => {
    splashWindow = null;
  });
}

function createMainWindow() {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 1024,
    minHeight: 700,
    show: false,
    backgroundColor: '#ffffff',
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  mainWindow.loadURL(config.frontendUrl);
  mainWindow.once('ready-to-show', () => {
    mainWindow.show();
    if (splashWindow && !splashWindow.isDestroyed()) splashWindow.close();
  });

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith('http://localhost') || url.startsWith('http://127.0.0.1')) {
      return { action: 'allow' };
    }
    shell.openExternal(url);
    return { action: 'deny' };
  });

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

function relayStatus(payload) {
  if (splashWindow && !splashWindow.isDestroyed()) {
    splashWindow.webContents.send('status:update', payload);
  }
}

serviceManager.on('status', relayStatus);

ipcMain.handle('splash:open-logs', () => {
  shell.openPath(paths.logsDir);
});

ipcMain.handle('splash:quit', () => {
  app.quit();
});

async function start() {
  fs.mkdirSync(paths.logsDir, { recursive: true });
  fs.mkdirSync(paths.userDataRoot, { recursive: true });

  createSplashWindow();

  try {
    await serviceManager.start();
    await serviceManager.waitForFrontend(config.frontendUrl, 120_000);
    createMainWindow();
  } catch (err) {
    console.error('[main] startup failed:', err);
    const detail = err && err.stack ? err.stack : String(err);
    dialog.showErrorBox('启动失败', `服务启动异常：\n\n${detail}\n\n日志目录：${paths.logsDir}`);
    app.quit();
  }
}

app.whenReady().then(start);

app.on('window-all-closed', () => {
  app.quit();
});

app.on('before-quit', async (event) => {
  if (serviceManager.isStopping || serviceManager.isStopped) return;
  event.preventDefault();
  await serviceManager.stop();
  app.exit(0);
});

process.on('uncaughtException', (err) => {
  console.error('[main] uncaught:', err);
});
