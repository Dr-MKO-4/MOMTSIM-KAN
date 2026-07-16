"use strict";
/**
 * main.js — Electron main process for MoMTSim.
 *
 * Flow:
 *  1. Show a splash screen immediately
 *  2. Spawn the PyInstaller backend (momtsim_server.exe)
 *  3. Poll /api/health until the server is ready (max ~30 s)
 *  4. Close splash, open the main BrowserWindow → http://127.0.0.1:PORT
 *  5. On quit: kill the backend process
 */

const { app, BrowserWindow, dialog } = require("electron");
const path  = require("path");
const http  = require("http");
const { spawn } = require("child_process");

const PORT = parseInt(process.env.MOMTSIM_PORT || "8765", 10);

let mainWindow    = null;
let splashWindow  = null;
let backendProcess = null;

// ── Path to backend executable ───────────────────────────────────────────────
function getBackendExe() {
  if (app.isPackaged) {
    // Installed app: backend lives in resources/backend/
    return path.join(process.resourcesPath, "backend", "momtsim_server.exe");
  }
  // Dev: PyInstaller output next to electron/
  return path.join(__dirname, "..", "dist", "momtsim_server", "momtsim_server.exe");
}

// ── Spawn the Python server ──────────────────────────────────────────────────
function startBackend() {
  const exe = getBackendExe();
  backendProcess = spawn(exe, [], {
    env: { ...process.env, MOMTSIM_PORT: String(PORT) },
    stdio: "ignore",
    windowsHide: true,   // hide any console window on Windows
    detached: false,
  });
  backendProcess.on("error", (err) => {
    console.error("Backend spawn error:", err.message);
  });
}

// ── Poll /api/health until the server responds ───────────────────────────────
function waitForBackend(maxRetries = 30, intervalMs = 1000) {
  return new Promise((resolve, reject) => {
    let tries = 0;

    const check = () => {
      const req = http.get(`http://127.0.0.1:${PORT}/api/health`, (res) => {
        if (res.statusCode === 200) {
          resolve();
        } else {
          retry();
        }
        res.resume(); // drain response
      });
      req.setTimeout(800, () => { req.destroy(); retry(); });
      req.on("error", retry);
    };

    const retry = () => {
      tries += 1;
      if (tries >= maxRetries) {
        reject(new Error(`Backend did not start after ${maxRetries} s`));
      } else {
        setTimeout(check, intervalMs);
      }
    };

    check();
  });
}

// ── Splash window ────────────────────────────────────────────────────────────
function createSplash() {
  splashWindow = new BrowserWindow({
    width: 480,
    height: 300,
    frame: false,
    resizable: false,
    center: true,
    alwaysOnTop: true,
    backgroundColor: "#0D0F18",
    webPreferences: { nodeIntegration: false, contextIsolation: true },
  });
  splashWindow.loadFile(path.join(__dirname, "loading.html"));
}

// ── Main window ──────────────────────────────────────────────────────────────
function createMain() {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 1024,
    minHeight: 700,
    show: false,
    title: "MoMTSim",
    backgroundColor: "#0D0F18",
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
    },
  });

  mainWindow.loadURL(`http://127.0.0.1:${PORT}`);

  mainWindow.once("ready-to-show", () => {
    if (splashWindow && !splashWindow.isDestroyed()) {
      splashWindow.close();
      splashWindow = null;
    }
    mainWindow.show();
    mainWindow.focus();
  });

  mainWindow.on("closed", () => {
    mainWindow = null;
  });

  // Open DevTools only in dev mode
  if (!app.isPackaged) {
    mainWindow.webContents.openDevTools({ mode: "detach" });
  }
}

// ── Kill backend on exit ─────────────────────────────────────────────────────
function killBackend() {
  if (backendProcess) {
    try { backendProcess.kill("SIGTERM"); } catch (_) { /* already dead */ }
    backendProcess = null;
  }
}

// ── App lifecycle ────────────────────────────────────────────────────────────
app.whenReady().then(async () => {
  createSplash();
  startBackend();

  try {
    await waitForBackend(30, 1000);
    createMain();
  } catch (err) {
    killBackend();
    dialog.showErrorBox(
      "MoMTSim — Erreur de démarrage",
      `Le serveur Python n'a pas pu démarrer.\n\n${err.message}\n\n` +
      "Vérifiez que le port 8765 n'est pas déjà utilisé."
    );
    app.quit();
  }
});

app.on("window-all-closed", () => {
  killBackend();
  app.quit();
});

app.on("before-quit", killBackend);
