#!/usr/bin/env node

const fs = require("fs");
const path = require("path");
const { spawnSync } = require("child_process");

const ROOT_DIR = path.resolve(__dirname, "..", "..");
const RUNTIME_ROOT = path.join(ROOT_DIR, "desktop", "python-runtime");
const VENV_DIR = path.join(RUNTIME_ROOT, "venv");
const BIN_DIR = path.join(RUNTIME_ROOT, "bin");
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
    return path.join(VENV_DIR, "Scripts", "python.exe");
  }
  return path.join(VENV_DIR, "bin", "python3");
}

function ensureCleanRuntimeDir() {
  if (fs.existsSync(RUNTIME_ROOT)) {
    fs.rmSync(RUNTIME_ROOT, { recursive: true, force: true });
  }
  fs.mkdirSync(RUNTIME_ROOT, { recursive: true });
  fs.mkdirSync(BIN_DIR, { recursive: true });
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
  runOrThrow(command, [...prefixArgs, "-m", "venv", VENV_DIR], { cwd: ROOT_DIR });

  const venvPython = getVenvPythonPath();
  if (!fs.existsSync(venvPython)) {
    throw new Error(`Bundled runtime python not found at ${venvPython}`);
  }

  runOrThrow(venvPython, ["-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"], {
    cwd: ROOT_DIR,
  });
  runOrThrow(venvPython, ["-m", "pip", "install", "-r", REQUIREMENTS_FILE], { cwd: ROOT_DIR });
  // Ensure pkg_resources remains available for manim plugins (manim-voiceover).
  runOrThrow(venvPython, ["-m", "pip", "install", "--upgrade", "setuptools<81"], {
    cwd: ROOT_DIR,
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

  console.log(`[desktop] bundled Python runtime ready at ${VENV_DIR}`);
  console.log(`[desktop] bundled ffmpeg ready at ${ffmpegTarget}`);
}

main();
