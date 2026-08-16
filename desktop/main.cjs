// desktop/main.cjs

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
const PYTHON_RUNTIME_PYTHON_DIR = IS_PACKAGED
  ? path.join(process.resourcesPath, "python-runtime", "python")
  : path.join(APP_DIR, "desktop", "python-runtime", "python");
const PYTHON_RUNTIME_BIN_DIR = IS_PACKAGED
  ? path.join(process.resourcesPath, "python-runtime", "bin")
  : path.join(APP_DIR, "desktop", "python-runtime", "bin");
const PLAYWRIGHT_BROWSERS_DIR = IS_PACKAGED
  ? path.join(process.resourcesPath, "python-runtime", "ms-playwright")
  : path.join(APP_DIR, "desktop", "python-runtime", "ms-playwright");
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
const KEYCHAIN_SERVICE = "UpcurvEd";
const SECURE_PROVIDER_KEY_FIELDS = ["claude", "gemini", "openai", "openrouter"];
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
  const safePayload = Object.fromEntries(
    SECURE_PROVIDER_KEY_FIELDS.map((provider) => [provider, String(source[provider] || "")])
  );
  safePayload.provider = String(source.provider || "");
  safePayload.model = String(source.model || "");
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

async function probeBackendHealth() {
  try {
    const payload = await httpGetJson(`http://${API_HOST}:${API_PORT}/health`, 1200);
    return payload && payload.ok === true ? payload : null;
  } catch {
    return null;
  }
}

// A healthy backend is only safe to adopt when it runs on this same OS. WSL2 mirrors
// localhost into Windows, so an installed Windows app will otherwise silently attach to a
// `desktop:dev` backend running in WSL and use its Python instead of the bundled runtime.
function resolveInterpreterPath(command) {
  const probe = runCapture(command, ["-c", "import sys; print(sys.executable)"]);
  if (probe.status !== 0) return null;
  return String(probe.stdout || "").trim() || null;
}

function samePath(left, right) {
  const a = path.resolve(left);
  const b = path.resolve(right);
  // Deliberately no realpathSync: a venv's python is a symlink to its base interpreter, and
  // collapsing them would make a base-interpreter backend look like a venv one.
  return process.platform === "win32" ? a.toLowerCase() === b.toLowerCase() : a === b;
}

function canAdoptBackend(payload) {
  const reported = typeof payload.platform === "string" ? payload.platform : "";
  // Backend predating the identity fields: trust it in dev, never in a packaged app.
  if (!reported) return IS_DEV;
  if (reported !== process.platform) return false;

  // Matching OS is not enough. A backend on a different interpreter has a different render stack
  // (a conda Python resolves a Cairo without tee-surface support) and a different snapshot of the
  // Python source, so adopting it silently runs code this app never selected. Refusing is cheap:
  // startBackend() just claims the next free port for its own.
  const theirs = typeof payload.interpreter === "string" ? payload.interpreter.trim() : "";
  if (!theirs) return true;
  const ours = resolveInterpreterPath(getPythonCommand());
  if (!ours) return true;
  return samePath(theirs, ours);
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

// A checked-out `.venv` is a deliberate statement about which interpreter this repo runs on, so
// it outranks whatever `python3` happens to resolve to. Bare `python3` is often a conda base env,
// and conda ships native libraries that shadow the host's -- a conda interpreter's RPATH is
// `$ORIGIN/../lib`, which makes Pycairo bind conda's tee-surface-less Cairo and fail with
// `undefined symbol: cairo_tee_surface_index` even though the system Cairo is fine.
function getProjectVenvPython() {
  const candidate =
    process.platform === "win32"
      ? path.join(APP_DIR, ".venv", "Scripts", "python.exe")
      : path.join(APP_DIR, ".venv", "bin", "python");
  return fs.existsSync(candidate) ? candidate : null;
}

function getPythonCommand() {
  if (process.env.PYTHON_BIN) return process.env.PYTHON_BIN;
  // Packaged builds must keep using their own runtime, so this stays ahead of the venv.
  const bundled = getBundledPythonPath();
  if (bundled) return bundled;
  const venv = getProjectVenvPython();
  if (venv) return venv;
  if (process.platform === "win32") return "python";
  if (canRun("python3.12", ["--version"])) return "python3.12";
  return "python3";
}

function getBundledPythonPath() {
  const candidates =
    process.platform === "win32"
      ? [path.join(PYTHON_RUNTIME_PYTHON_DIR, "python.exe")]
      : [
          path.join(PYTHON_RUNTIME_PYTHON_DIR, "bin", "python3"),
          path.join(PYTHON_RUNTIME_PYTHON_DIR, "bin", "python"),
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
      const health = await probeBackendHealth();
      const adoptable = Boolean(health) && canAdoptBackend(health);

      if (health && !adoptable) {
        console.warn(
          `[desktop] refusing to adopt the backend at ${API_HOST}:${API_PORT}: it reports platform '${
            health.platform || "unknown"
          }' on interpreter '${health.interpreter || "unknown"}', but this app runs '${
            process.platform
          }' on '${resolveInterpreterPath(getPythonCommand()) || getPythonCommand()}'.`
        );
      }

      if (adoptable && IS_DEV && !REUSE_EXISTING_SERVERS) {
        throw new Error(
          `Backend port ${API_PORT} is already in use. Close existing dev servers and rerun desktop:dev, or set DESKTOP_REUSE_EXISTING_SERVERS=1 to allow reuse.`
        );
      }

      if (adoptable) {
        console.log(`[desktop] reusing backend at ${API_HOST}:${API_PORT}`);
        return;
      }

      // Foreign, unhealthy, or cross-OS occupant: leave it alone and take our own port.
      const fallbackPort = await findOpenPort(API_PORT + 1, API_HOST);
      console.warn(
        `[desktop] port ${API_PORT} is not usable by this app; starting our own backend on ${API_HOST}:${fallbackPort}`
      );
      API_PORT = fallbackPort;
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
      UPCURVED_FFMPEG_PATH: bundledFfmpeg || process.env.UPCURVED_FFMPEG_PATH,
      IMAGEIO_FFMPEG_EXE: bundledFfmpeg || process.env.IMAGEIO_FFMPEG_EXE,
      FFMPEG_BINARY: bundledFfmpeg || process.env.FFMPEG_BINARY,
      UPCURVED_DISABLE_LATEX: process.env.UPCURVED_DISABLE_LATEX || "1",
      PYTHONPATH: isUsingBundledPython
        ? BACKEND_ROOT_DIR
        : process.env.PYTHONPATH
          ? `${BACKEND_ROOT_DIR}${path.delimiter}${process.env.PYTHONPATH}`
          : BACKEND_ROOT_DIR,
      APP_MODE: process.env.APP_MODE || "desktop-local",
      UPCURVED_STORAGE_DIR: process.env.UPCURVED_STORAGE_DIR || storageDir,
      UPCURVED_DESKTOP_STATE_DIR: process.env.UPCURVED_DESKTOP_STATE_DIR || desktopStateDir,
      PLAYWRIGHT_BROWSERS_PATH:
        process.env.PLAYWRIGHT_BROWSERS_PATH || PLAYWRIGHT_BROWSERS_DIR,
    };

    // AppImage's launcher puts its native libraries first in LD_LIBRARY_PATH. Those libraries
    // are meant for Electron, and allowing bundled Python to inherit them can make Pycairo bind
    // to an incompatible Cairo build (for example: undefined symbol cairo_tee_surface_index).
    // Python's packaged executable has its own RPATH, while Manim's Cairo/Pango dependencies
    // should resolve from the Linux host.
    if (process.platform === "linux" && isUsingBundledPython) {
      delete backendEnv.LD_LIBRARY_PATH;
      delete backendEnv.LD_PRELOAD;
      backendEnv.UPCURVED_CLEAN_LINUX_LOADER_ENV = "1";
    }

    if (isUsingBundledPython) {
      // Force the packaged interpreter to use only its own stdlib and site-packages.
      backendEnv.PYTHONHOME = PYTHON_RUNTIME_PYTHON_DIR;
      backendEnv.PYTHONNOUSERSITE = "1";
      backendEnv.PYTHONSAFEPATH = "1";
      delete backendEnv.VIRTUAL_ENV;
      delete backendEnv.__PYVENV_LAUNCHER__;
      delete backendEnv.PYTHONEXECUTABLE;

      const preflightCode = [
        "import sys, pathlib, ctypes, _ctypes",
        "import cairo, numpy, scipy, manim, manim_voiceover",
        "import edge_tts",
        "from backend.tts.manim_service import EdgeTTSService",
        "import backend.api.main as backend_main",
        "surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1)",
        "tee = cairo.TeeSurface(surface)",
        "tee.index(0)",
        "root = pathlib.Path(sys.executable).resolve().parent if sys.platform == 'win32' else pathlib.Path(sys.executable).resolve().parents[1]",
        "inside = lambda value: pathlib.Path(value).resolve() == root or root in pathlib.Path(value).resolve().parents",
        "assert pathlib.Path(sys.prefix).resolve() == root, (sys.prefix, root)",
        "assert pathlib.Path(sys.base_prefix).resolve() == root, (sys.base_prefix, root)",
        "modules = {'_ctypes': _ctypes, 'cairo': cairo, 'numpy': numpy, 'scipy': scipy, 'manim': manim, 'manim_voiceover': manim_voiceover}",
        // Statically linked extensions have no __file__ (python-build-standalone compiles _ctypes
        // into the interpreter). Tolerate that, but require them to be genuinely built in.
        "located = {name: getattr(module, '__file__', None) for name, module in modules.items()}",
        "embedded = sorted(name for name, value in located.items() if value is None)",
        "assert all(name in sys.builtin_module_names for name in embedded), embedded",
        "bad = {name: value for name, value in located.items() if value and not inside(value)}",
        "assert not bad, bad",
        "outside_site = [p for p in sys.path if p and 'site-packages' in p and not inside(p)]",
        "assert not outside_site, outside_site",
        "print(sys.version)",
        "print('executable', sys.executable)",
        "print('prefix', sys.prefix)",
        "print('scipy', scipy.__file__)",
        "print('backend_ok', bool(backend_main))",
      ].join("; ");
      const preflight = runCapture(
        python,
        ["-c", preflightCode],
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
