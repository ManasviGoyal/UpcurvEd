const { app, BrowserWindow, dialog, ipcMain } = require("electron");
const path = require("path");
const fs = require("fs");
const http = require("http");
const net = require("net");
const { spawn, spawnSync } = require("child_process");

let keytar = null;
try {
  // Native keychain adapter used in packaged desktop builds.
  keytar = require("keytar");
} catch (err) {
  console.warn("[desktop] keytar unavailable; secure key storage will fall back to local settings.");
}

const IS_DEV = process.argv.includes("--dev") || process.env.ELECTRON_DEV === "1";
const IS_PACKAGED = app.isPackaged;
const APP_DIR = path.resolve(__dirname, "..");
const BACKEND_ROOT_DIR = IS_PACKAGED
  ? path.join(process.resourcesPath, "app.asar.unpacked")
  : APP_DIR;
const PYTHON_RUNTIME_VENV_DIR = IS_PACKAGED
  ? path.join(process.resourcesPath, "python-runtime", "venv")
  : path.join(APP_DIR, "desktop", "python-runtime", "venv");
const PYTHON_RUNTIME_BIN_DIR = IS_PACKAGED
  ? path.join(process.resourcesPath, "python-runtime", "bin")
  : path.join(APP_DIR, "desktop", "python-runtime", "bin");
const IS_WSL =
  process.platform === "linux" &&
  (Boolean(process.env.WSL_DISTRO_NAME) || fs.existsSync("/proc/sys/fs/binfmt_misc/WSLInterop"));

const API_HOST = "127.0.0.1";
let API_PORT = Number(process.env.DESKTOP_API_PORT || 8000);
const UI_HOST = "127.0.0.1";
const UI_PORT = 8080;
const REUSE_EXISTING_SERVERS = process.env.DESKTOP_REUSE_EXISTING_SERVERS !== "0";
const BACKEND_RELOAD = process.env.DESKTOP_BACKEND_RELOAD === "1";

let backendProcess = null;
let frontendDevProcess = null;
let staticServer = null;
let isShuttingDown = false;
const KEYCHAIN_SERVICE = "UpcurvEdDesktop";
let keytarErrorLogged = false;
let backendLogTail = "";
const BACKEND_LOG_TAIL_MAX = 12000;

function disableKeytarFallback(reason, err) {
  if (!keytarErrorLogged) {
    const message = err && err.message ? err.message : String(err || "unknown error");
    console.warn(`[desktop] keytar ${reason}; falling back to local settings. ${message}`);
    keytarErrorLogged = true;
  }
  keytar = null;
}

function normalizeAccount(account) {
  if (!account) return "default";
  return String(account).trim().toLowerCase().slice(0, 256) || "default";
}

async function getSecureApiKeys(account) {
  if (!keytar) return null;
  try {
    const raw = await keytar.getPassword(KEYCHAIN_SERVICE, normalizeAccount(account));
    if (!raw) return null;
    try {
      return JSON.parse(raw);
    } catch {
      return null;
    }
  } catch (err) {
    disableKeytarFallback("read unavailable", err);
    return null;
  }
}

async function setSecureApiKeys(account, payload) {
  if (!keytar) return { ok: false, reason: "keytar_unavailable" };
  const normalized = normalizeAccount(account);
  const source = payload || {};
  const safePayload = {
    claude: String(source.claude || ""),
    gemini: String(source.gemini || ""),
    provider: String(source.provider || ""),
    model: String(source.model || ""),
  };
  try {
    await keytar.setPassword(KEYCHAIN_SERVICE, normalized, JSON.stringify(safePayload));
    return { ok: true };
  } catch (err) {
    disableKeytarFallback("write unavailable", err);
    return { ok: false, reason: "keytar_unavailable" };
  }
}

async function clearSecureApiKeys(account) {
  if (!keytar) return { ok: false, reason: "keytar_unavailable" };
  try {
    await keytar.deletePassword(KEYCHAIN_SERVICE, normalizeAccount(account));
    return { ok: true };
  } catch (err) {
    disableKeytarFallback("delete unavailable", err);
    return { ok: false, reason: "keytar_unavailable" };
  }
}

ipcMain.handle("secure-store:get-api-keys", async (_event, account) => {
  return getSecureApiKeys(account);
});

ipcMain.handle("secure-store:set-api-keys", async (_event, body) => {
  const safeBody = body || {};
  return setSecureApiKeys(safeBody.account, safeBody.payload);
});

ipcMain.handle("secure-store:clear-api-keys", async (_event, account) => {
  return clearSecureApiKeys(account);
});

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function canRun(command, args) {
  const result = spawnSync(command, args, {
    stdio: "ignore",
  });
  return result.status === 0;
}

function httpGetJson(url, timeoutMs = 1200) {
  return new Promise((resolve, reject) => {
    const req = http.get(url, { timeout: timeoutMs }, (res) => {
      let body = "";
      res.setEncoding("utf8");
      res.on("data", (chunk) => {
        body += chunk;
      });
      res.on("end", () => {
        if (res.statusCode < 200 || res.statusCode >= 300) {
          reject(new Error(`HTTP ${res.statusCode}`));
          return;
        }
        try {
          resolve(JSON.parse(body));
        } catch (err) {
          reject(new Error("invalid_json_response"));
        }
      });
    });
    req.on("timeout", () => {
      req.destroy(new Error("timeout"));
    });
    req.on("error", (err) => reject(err));
  });
}

async function isHealthyBackendRunning() {
  try {
    const payload = await httpGetJson(`http://${API_HOST}:${API_PORT}/health`, 1200);
    return Boolean(payload && payload.ok === true);
  } catch {
    return false;
  }
}

function isPortOpen(port, host, timeoutMs = 600) {
  return new Promise((resolve) => {
    const socket = new net.Socket();
    let settled = false;

    const settle = (value) => {
      if (settled) return;
      settled = true;
      socket.destroy();
      resolve(value);
    };

    socket.setTimeout(timeoutMs);
    socket.once("connect", () => settle(true));
    socket.once("error", () => settle(false));
    socket.once("timeout", () => settle(false));

    socket.connect(port, host);
  });
}

function canBindPort(port, host) {
  return new Promise((resolve) => {
    const tester = net.createServer();
    tester.unref();
    tester.once("error", () => resolve(false));
    tester.listen(port, host, () => {
      tester.close(() => resolve(true));
    });
  });
}

async function findOpenPort(startPort, host, maxAttempts = 25) {
  let port = startPort;
  for (let i = 0; i < maxAttempts; i += 1, port += 1) {
    // Skip ports already in use quickly before trying bind probe.
    if (await isPortOpen(port, host, 250)) continue;
    if (await canBindPort(port, host)) return port;
  }
  throw new Error(`No free backend port found near ${startPort}.`);
}

async function waitForPort(port, host, timeoutMs, label) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    if (await isPortOpen(port, host, 600)) {
      return;
    }
    await sleep(300);
  }
  throw new Error(`${label} did not become available at ${host}:${port} in time.`);
}

async function waitForBackendStartup(proc, port, host, timeoutMs) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    if (await isPortOpen(port, host, 500)) return;
    if (proc && proc.exitCode !== null) {
      const tail = (backendLogTail || "").trim();
      if (tail) {
        throw new Error(
          `Backend process exited early (code=${proc.exitCode}).\n\nRecent backend logs:\n${tail.slice(
            -5000
          )}`
        );
      }
      throw new Error(`Backend process exited early (code=${proc.exitCode}).`);
    }
    await sleep(250);
  }
  throw new Error(`Backend did not become available at ${host}:${port} in time.`);
}

function runCapture(command, args, options = {}) {
  return spawnSync(command, args, {
    encoding: "utf8",
    ...options,
  });
}

function getPythonCommand() {
  if (process.env.PYTHON_BIN) return process.env.PYTHON_BIN;
  const bundled = getBundledPythonPath();
  if (bundled) return bundled;
  if (process.platform === "win32") return "python";
  if (canRun("python3.12", ["--version"])) return "python3.12";
  return "python3";
}

function getBundledPythonPath() {
  const candidates =
    process.platform === "win32"
      ? [path.join(PYTHON_RUNTIME_VENV_DIR, "Scripts", "python.exe")]
      : [
          path.join(PYTHON_RUNTIME_VENV_DIR, "bin", "python3"),
          path.join(PYTHON_RUNTIME_VENV_DIR, "bin", "python"),
        ];

  for (const candidate of candidates) {
    if (fs.existsSync(candidate)) {
      return candidate;
    }
  }

  return null;
}

function getBundledFfmpegPath() {
  const candidates =
    process.platform === "win32"
      ? [path.join(PYTHON_RUNTIME_BIN_DIR, "ffmpeg.exe")]
      : [path.join(PYTHON_RUNTIME_BIN_DIR, "ffmpeg")];

  for (const candidate of candidates) {
    if (fs.existsSync(candidate)) {
      return candidate;
    }
  }

  return null;
}

function getNpmCommand() {
  return process.platform === "win32" ? "npm.cmd" : "npm";
}

function spawnManagedProcess(command, args, name, options = {}) {
  const child = spawn(command, args, {
    cwd: APP_DIR,
    env: process.env,
    stdio: ["ignore", "pipe", "pipe"],
    detached: process.platform !== "win32",
    ...options,
  });

  if (child.stdout) {
    child.stdout.on("data", (buf) => {
      if (name === "backend") {
        backendLogTail = `${backendLogTail}${String(buf)}`.slice(-BACKEND_LOG_TAIL_MAX);
      }
      process.stdout.write(`[${name}] ${buf}`);
    });
  }
  if (child.stderr) {
    child.stderr.on("data", (buf) => {
      if (name === "backend") {
        backendLogTail = `${backendLogTail}${String(buf)}`.slice(-BACKEND_LOG_TAIL_MAX);
      }
      process.stderr.write(`[${name}] ${buf}`);
    });
  }

  child.on("exit", (code, signal) => {
    if (!isShuttingDown) {
      console.error(`[${name}] exited (code=${code}, signal=${signal || "none"})`);
    }
  });

  return child;
}

function startBackend() {
  return (async () => {
    if (await isPortOpen(API_PORT, API_HOST, 500)) {
      const healthy = await isHealthyBackendRunning();
      if (!healthy) {
        if (IS_DEV) {
          const fallbackPort = await findOpenPort(API_PORT + 1, API_HOST);
          console.warn(
            `[desktop] port ${API_PORT} is busy with a non-UpcurvEd process; switching backend to ${API_HOST}:${fallbackPort}`
          );
          API_PORT = fallbackPort;
        } else {
          throw new Error(
            `Port ${API_PORT} is occupied by a non-UpcurvEd or unhealthy process. Stop whatever is using ${API_HOST}:${API_PORT} and rerun desktop.`
          );
        }
      }
      if (healthy && IS_DEV && !REUSE_EXISTING_SERVERS) {
        throw new Error(
          `Backend port ${API_PORT} is already in use. Close existing dev servers and rerun desktop:dev, or set DESKTOP_REUSE_EXISTING_SERVERS=1 to allow reuse.`
        );
      }
      if (healthy) {
        console.log(`[desktop] reusing backend at ${API_HOST}:${API_PORT}`);
        return;
      }
    }

    // Final guard against bind races.
    if (!(await canBindPort(API_PORT, API_HOST))) {
      const fallbackPort = await findOpenPort(API_PORT + 1, API_HOST);
      console.warn(
        `[desktop] backend port ${API_PORT} became unavailable; switching to ${API_HOST}:${fallbackPort}`
      );
      API_PORT = fallbackPort;
    }

    const python = getPythonCommand();
    const args = [
      "-m",
      "uvicorn",
      "backend.api.main:app",
      "--host",
      API_HOST,
      "--port",
      String(API_PORT),
    ];
    if (IS_DEV && BACKEND_RELOAD) {
      args.push("--reload", "--reload-dir", "backend");
    }

    const bundledPython = getBundledPythonPath();
    const bundledFfmpeg = getBundledFfmpegPath();
    const isUsingBundledPython = Boolean(bundledPython && bundledPython === python);
    const desktopDataDir = app.getPath("userData");
    const storageDir = path.join(desktopDataDir, "storage");
    const desktopStateDir = path.join(desktopDataDir, "state");
    try {
      fs.mkdirSync(storageDir, { recursive: true });
      fs.mkdirSync(desktopStateDir, { recursive: true });
    } catch (_) {
      // Best effort; backend will fall back if needed.
    }
    console.log(`[desktop] storage dir: ${storageDir}`);
    console.log(`[desktop] state dir: ${desktopStateDir}`);
    const backendPath = isUsingBundledPython
      ? `${path.dirname(python)}${path.delimiter}${PYTHON_RUNTIME_BIN_DIR}${path.delimiter}${
          process.env.PATH || ""
        }`
      : process.env.PATH;
    const backendEnv = {
      ...process.env,
      PATH: backendPath,
      VIRTUAL_ENV: isUsingBundledPython ? PYTHON_RUNTIME_VENV_DIR : process.env.VIRTUAL_ENV,
      UPCURVED_FFMPEG_PATH: bundledFfmpeg || process.env.UPCURVED_FFMPEG_PATH,
      IMAGEIO_FFMPEG_EXE: bundledFfmpeg || process.env.IMAGEIO_FFMPEG_EXE,
      FFMPEG_BINARY: bundledFfmpeg || process.env.FFMPEG_BINARY,
      UPCURVED_DISABLE_LATEX: process.env.UPCURVED_DISABLE_LATEX || "1",
      PYTHONPATH: process.env.PYTHONPATH
        ? `${BACKEND_ROOT_DIR}${path.delimiter}${process.env.PYTHONPATH}`
        : BACKEND_ROOT_DIR,
      APP_MODE: process.env.APP_MODE || "desktop-local",
      UPCURVED_STORAGE_DIR: process.env.UPCURVED_STORAGE_DIR || storageDir,
      UPCURVED_DESKTOP_STATE_DIR: process.env.UPCURVED_DESKTOP_STATE_DIR || desktopStateDir,
    };

    if (isUsingBundledPython) {
      const preflight = runCapture(
        python,
        ["-c", "import sys; import backend.api.main as m; print(sys.version); print('backend_ok', bool(m))"],
        { cwd: BACKEND_ROOT_DIR, env: backendEnv }
      );
      if (preflight.status !== 0) {
        const details = `${preflight.stdout || ""}\n${preflight.stderr || ""}`.trim();
        throw new Error(
          `Bundled backend runtime preflight failed.\n${details || "No Python stderr/stdout captured."}`
        );
      }
    }

    backendLogTail = "";
    backendProcess = spawnManagedProcess(python, args, "backend", {
      cwd: BACKEND_ROOT_DIR,
      env: backendEnv,
    });

    await waitForBackendStartup(backendProcess, API_PORT, API_HOST, 90000);
  })();
}

function startFrontendDevServer() {
  return (async () => {
    if (await isPortOpen(UI_PORT, UI_HOST, 500)) {
      if (IS_DEV && !REUSE_EXISTING_SERVERS) {
        throw new Error(
          `Frontend dev server port ${UI_PORT} is already in use. Close existing Vite dev server and rerun desktop:dev, or set DESKTOP_REUSE_EXISTING_SERVERS=1 to allow reuse.`
        );
      }
      console.log(`[desktop] reusing frontend dev server at ${UI_HOST}:${UI_PORT}`);
      return;
    }

    const npm = getNpmCommand();
    const args = [
      "--prefix",
      "frontend",
      "run",
      "dev",
      "--",
      "--host",
      UI_HOST,
      "--port",
      String(UI_PORT),
    ];

    frontendDevProcess = spawnManagedProcess(npm, args, "frontend-dev", {
      env: {
        ...process.env,
        VITE_API_BASE_URL: `http://${API_HOST}:${API_PORT}`,
        VITE_APP_MODE: process.env.VITE_APP_MODE || "desktop-local",
      },
    });

    await waitForPort(UI_PORT, UI_HOST, 90000, "Frontend dev server");
  })();
}

function contentTypeFor(filePath) {
  const ext = path.extname(filePath).toLowerCase();
  const map = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".mjs": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
  };
  return map[ext] || "application/octet-stream";
}

function startStaticServer() {
  return new Promise(async (resolve, reject) => {
    if (await isPortOpen(UI_PORT, UI_HOST, 500)) {
      console.log(`[desktop] reusing static UI server at ${UI_HOST}:${UI_PORT}`);
      resolve();
      return;
    }

    const distDir = path.join(APP_DIR, "frontend", "dist");
    const indexFile = path.join(distDir, "index.html");

    if (!fs.existsSync(indexFile)) {
      reject(
        new Error(
          "Missing frontend build output. Run `npm run desktop:build:frontend` first."
        )
      );
      return;
    }

    staticServer = http.createServer((req, res) => {
      try {
        const requestUrl = new URL(req.url || "/", `http://${UI_HOST}:${UI_PORT}`);
        const cleanPath = decodeURIComponent(requestUrl.pathname);
        const relativePath = cleanPath === "/" ? "index.html" : cleanPath.replace(/^\//, "");
        const candidate = path.resolve(distDir, relativePath);
        const inDist = candidate === distDir || candidate.startsWith(`${distDir}${path.sep}`);

        let filePath = candidate;
        if (!inDist) {
          res.statusCode = 403;
          res.end("Forbidden");
          return;
        }

        if (!fs.existsSync(filePath) || fs.statSync(filePath).isDirectory()) {
          filePath = indexFile;
        }

        fs.readFile(filePath, (readErr, data) => {
          if (readErr) {
            res.statusCode = 500;
            res.end("Internal server error");
            return;
          }
          res.setHeader("Content-Type", contentTypeFor(filePath));
          res.end(data);
        });
      } catch (err) {
        res.statusCode = 500;
        res.end("Internal server error");
      }
    });

    staticServer.once("error", (err) => reject(err));
    staticServer.listen(UI_PORT, UI_HOST, () => {
      console.log(`[desktop] static UI server listening on http://${UI_HOST}:${UI_PORT}`);
      resolve();
    });
  });
}

function killProcessTree(proc) {
  if (!proc || proc.killed) return;

  if (process.platform === "win32") {
    const killer = spawn("taskkill", ["/pid", String(proc.pid), "/t", "/f"]);
    killer.on("error", () => {
      try {
        proc.kill("SIGTERM");
      } catch (_) {
        // no-op
      }
    });
    return;
  }

  try {
    process.kill(-proc.pid, "SIGTERM");
  } catch (_) {
    try {
      proc.kill("SIGTERM");
    } catch (_) {
      // no-op
    }
  }
}

async function shutdown() {
  if (isShuttingDown) return;
  isShuttingDown = true;

  try {
    if (staticServer) {
      await new Promise((resolve) => {
        staticServer.close(() => resolve());
      });
      staticServer = null;
    }
  } catch (_) {
    // no-op
  }

  killProcessTree(frontendDevProcess);
  killProcessTree(backendProcess);

  frontendDevProcess = null;
  backendProcess = null;
}

function createWindow() {
  const runtimeApiBaseUrl = `http://${API_HOST}:${API_PORT}`;
  const mainWindow = new BrowserWindow({
    width: 1500,
    height: 920,
    minWidth: 1200,
    minHeight: 760,
    show: false,
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      additionalArguments: [`--upcurved-api-base-url=${runtimeApiBaseUrl}`],
    },
  });

  mainWindow.once("ready-to-show", () => {
    mainWindow.show();
  });

  mainWindow.loadURL(`http://${UI_HOST}:${UI_PORT}`);
}

async function bootstrap() {
  // WSL needs a GUI display (typically via WSLg). Fail fast with a clear message.
  if (IS_WSL && !process.env.DISPLAY && !process.env.WAYLAND_DISPLAY) {
    throw new Error(
      "WSL GUI display not detected. Install/enable WSLg or use the native Windows installer."
    );
  }
  await startBackend();
  if (IS_DEV) {
    await startFrontendDevServer();
  } else {
    await startStaticServer();
  }
  createWindow();
}

app.whenReady().then(async () => {
  try {
    await bootstrap();
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    dialog.showErrorBox("Desktop startup failed", msg);
    await shutdown();
    app.quit();
  }
});

app.on("before-quit", () => {
  void shutdown();
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});

app.on("activate", () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    createWindow();
  }
});
