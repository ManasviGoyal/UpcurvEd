#!/usr/bin/env node

const fs = require("fs");
const path = require("path");
const { spawnSync } = require("child_process");

const ROOT_DIR = path.resolve(__dirname, "..", "..");
const RUNTIME_ROOT = path.join(ROOT_DIR, "desktop", "python-runtime");
const PYTHON_DIR = path.join(RUNTIME_ROOT, "python");
const BIN_DIR = path.join(RUNTIME_ROOT, "bin");
const PLAYWRIGHT_BROWSERS_DIR = path.join(RUNTIME_ROOT, "ms-playwright");
const REQUIREMENTS_FILE = path.join(ROOT_DIR, "desktop", "requirements-desktop.txt");

function runOrThrow(command, args, options = {}) {
  const result = spawnSync(command, args, {
    stdio: "inherit",
    ...options,
  });

  if (result.status !== 0) {
    throw new Error(`Command failed (${result.status}): ${command} ${args.join(" ")}`);
  }
}

function runAndCaptureOrThrow(command, args, options = {}) {
  const result = spawnSync(command, args, {
    encoding: "utf8",
    ...options,
  });
  if (result.status !== 0) {
    throw new Error(
      `Command failed (${result.status}): ${command} ${args.join(" ")}\n${
        result.stderr || ""
      }`
    );
  }
  return (result.stdout || "").trim();
}

function canRun(command, args) {
  const result = spawnSync(command, args, {
    stdio: "ignore",
  });
  return result.status === 0;
}

function resolvePythonCommand() {
  if (process.env.PYTHON_BIN) {
    return { command: process.env.PYTHON_BIN, prefixArgs: [] };
  }

  if (process.platform === "win32") {
    if (canRun("py", ["-3.12", "--version"])) {
      return { command: "py", prefixArgs: ["-3.12"] };
    }
    if (canRun("py", ["-3", "--version"])) {
      return { command: "py", prefixArgs: ["-3"] };
    }
    return { command: "python", prefixArgs: [] };
  }

  if (canRun("python3.12", ["--version"])) {
    return { command: "python3.12", prefixArgs: [] };
  }
  if (canRun("python3", ["--version"])) {
    return { command: "python3", prefixArgs: [] };
  }
  return { command: "python", prefixArgs: [] };
}

function getVenvPythonPath() {
  if (process.platform === "win32") {
    return path.join(PYTHON_DIR, "python.exe");
  }
  const py3 = path.join(PYTHON_DIR, "bin", "python3");
  if (fs.existsSync(py3)) return py3;
  return path.join(PYTHON_DIR, "bin", "python");
}

function ensureCleanRuntimeDir() {
  if (fs.existsSync(RUNTIME_ROOT)) {
    fs.rmSync(RUNTIME_ROOT, { recursive: true, force: true });
  }
  fs.mkdirSync(RUNTIME_ROOT, { recursive: true });
  fs.mkdirSync(BIN_DIR, { recursive: true });
}

function copyPythonRuntime(command, prefixArgs) {
  const basePrefix = runAndCaptureOrThrow(
    command,
    [...prefixArgs, "-c", "import sys; print(sys.base_prefix)"],
    { cwd: ROOT_DIR }
  );
  if (!basePrefix || !fs.existsSync(basePrefix)) {
    throw new Error(`Could not resolve Python base runtime at: ${basePrefix}`);
  }

  if (!fs.cpSync) {
    throw new Error("Node runtime does not support fs.cpSync; need Node 16.7+.");
  }

  // Dereference symlinks so packaged app bundles do not contain host-specific link targets.
  fs.cpSync(basePrefix, PYTHON_DIR, { recursive: true, force: true, dereference: true });
}

function main() {
  if (!fs.existsSync(REQUIREMENTS_FILE)) {
    throw new Error(`Missing requirements file at ${REQUIREMENTS_FILE}`);
  }

  const { command, prefixArgs } = resolvePythonCommand();
  console.log(`[desktop] preparing bundled Python runtime with '${command}'`);

  // Desktop runtime is validated for Python 3.12 to keep binary deps stable across OS builds.
  const pickedVersion = runAndCaptureOrThrow(
    command,
    [...prefixArgs, "-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"],
    { cwd: ROOT_DIR }
  );
  if (pickedVersion !== "3.12") {
    throw new Error(
      `Python 3.12 is required for desktop runtime bundling. Found ${pickedVersion} via '${command}'. ` +
        `This step is for installer/release builds. You can still run local desktop dev with 'npm run desktop:dev'.`
    );
  }

  ensureCleanRuntimeDir();
  // Build a portable Python runtime copy (not venv) so end-user machines
  // do not depend on build host paths.
  copyPythonRuntime(command, prefixArgs);

  const venvPython = getVenvPythonPath();
  if (!fs.existsSync(venvPython)) {
    throw new Error(`Bundled runtime python not found at ${venvPython}.`);
  }

  // Ensure pip is present in copied runtime.
  runOrThrow(venvPython, ["-m", "ensurepip", "--upgrade"], { cwd: ROOT_DIR });
  runOrThrow(venvPython, ["-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"], {
    cwd: ROOT_DIR,
  });
  runOrThrow(venvPython, ["-m", "pip", "install", "-r", REQUIREMENTS_FILE], { cwd: ROOT_DIR });
  // Ensure pkg_resources remains available for manim plugins (manim-voiceover).
  runOrThrow(venvPython, ["-m", "pip", "install", "--upgrade", "setuptools<81"], {
    cwd: ROOT_DIR,
  });
  // Bundle Playwright Chromium into runtime so end-users do not need manual install.
  runOrThrow(venvPython, ["-m", "playwright", "install", "chromium"], {
    cwd: ROOT_DIR,
    env: {
      ...process.env,
      PLAYWRIGHT_BROWSERS_PATH: PLAYWRIGHT_BROWSERS_DIR,
    },
  });
  runOrThrow(venvPython, ["-m", "manim", "--version"], { cwd: ROOT_DIR });

  const ffmpegSource = runAndCaptureOrThrow(
    venvPython,
    ["-c", "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())"],
    { cwd: ROOT_DIR }
  );
  if (!ffmpegSource || !fs.existsSync(ffmpegSource)) {
    throw new Error(`Could not locate bundled ffmpeg binary from imageio-ffmpeg at ${ffmpegSource}`);
  }

  const ffmpegTarget = path.join(BIN_DIR, process.platform === "win32" ? "ffmpeg.exe" : "ffmpeg");
  fs.copyFileSync(ffmpegSource, ffmpegTarget);
  if (process.platform !== "win32") {
    fs.chmodSync(ffmpegTarget, 0o755);
  }

  console.log(`[desktop] bundled Python runtime ready at ${PYTHON_DIR}`);
  console.log(`[desktop] bundled ffmpeg ready at ${ffmpegTarget}`);
  console.log(`[desktop] bundled Playwright browsers ready at ${PLAYWRIGHT_BROWSERS_DIR}`);
}

main();
