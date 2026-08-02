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

function runAndCapture(command, args, options = {}) {
  return spawnSync(command, args, {
    encoding: "utf8",
    ...options,
  });
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

function getBundledPythonPath() {
  if (process.platform === "win32") {
    return path.join(PYTHON_DIR, "python.exe");
  }
  const py3 = path.join(PYTHON_DIR, "bin", "python3");
  if (fs.existsSync(py3)) return py3;
  return path.join(PYTHON_DIR, "bin", "python");
}

function bundledPythonEnv(extra = {}) {
  const env = {
    ...process.env,
    ...extra,
    PYTHONHOME: PYTHON_DIR,
    PYTHONNOUSERSITE: "1",
    PYTHONSAFEPATH: "1",
    PYTHONPATH: "",
  };
  delete env.VIRTUAL_ENV;
  delete env.__PYVENV_LAUNCHER__;
  delete env.PYTHONEXECUTABLE;
  return env;
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
  return basePrefix;
}

function walkRuntimeBinaryCandidates(rootDir) {
  const output = [];
  const stack = [rootDir];
  while (stack.length) {
    const current = stack.pop();
    for (const entry of fs.readdirSync(current, { withFileTypes: true })) {
      const fullPath = path.join(current, entry.name);
      if (entry.isDirectory()) {
        stack.push(fullPath);
        continue;
      }
      if (!entry.isFile()) continue;
      const lower = entry.name.toLowerCase();
      const inBin = fullPath.startsWith(path.join(PYTHON_DIR, "bin") + path.sep);
      if (
        entry.name === "Python" ||
        lower.endsWith(".so") ||
        lower.endsWith(".dylib") ||
        lower.endsWith(".bundle") ||
        inBin
      ) {
        output.push(fullPath);
      }
    }
  }
  return output;
}

function patchMacPythonFrameworkLinks() {
  if (process.platform !== "darwin") return;
  const otool = "/usr/bin/otool";
  const installNameTool = "/usr/bin/install_name_tool";
  if (!fs.existsSync(otool) || !fs.existsSync(installNameTool)) {
    throw new Error(
      "macOS desktop runtime bundling requires otool and install_name_tool. " +
        "Install the Xcode Command Line Tools and rerun the release build."
    );
  }

  const bundledLibrary = path.join(PYTHON_DIR, "Python");
  if (!fs.existsSync(bundledLibrary)) {
    throw new Error(`Bundled Python framework library is missing: ${bundledLibrary}`);
  }

  runOrThrow(installNameTool, ["-id", "@rpath/Python", bundledLibrary]);

  let patched = 0;
  for (const candidate of walkRuntimeBinaryCandidates(PYTHON_DIR)) {
    const inspected = runAndCapture(otool, ["-L", candidate]);
    if (inspected.status !== 0) continue;

    const dependencies = String(inspected.stdout || "")
      .split(/\r?\n/)
      .slice(1)
      .map((line) => line.trim().split(" ")[0])
      .filter(Boolean);

    for (const dependency of dependencies) {
      if (!dependency.includes("Python.framework/Versions/3.12/Python")) continue;
      const inBin = candidate.startsWith(path.join(PYTHON_DIR, "bin") + path.sep);
      const replacement = inBin
        ? "@executable_path/../Python"
        : `@loader_path/${path.relative(path.dirname(candidate), bundledLibrary)}`;
      runOrThrow(installNameTool, ["-change", dependency, replacement, candidate]);
      patched += 1;
    }
  }
  console.log(`[desktop] patched ${patched} macOS Python framework link(s)`);
}

function validateBundledRuntime(python) {
  const validationCode = [
    "import sys, pathlib, ctypes, _ctypes",
    "import numpy, scipy, manim, manim_voiceover",
    "from manim_voiceover.services.gtts import GTTSService",
    "import edge_tts",
    "root = pathlib.Path(sys.executable).resolve().parent if sys.platform == 'win32' else pathlib.Path(sys.executable).resolve().parents[1]",
    "inside = lambda value: pathlib.Path(value).resolve() == root or root in pathlib.Path(value).resolve().parents",
    "assert pathlib.Path(sys.prefix).resolve() == root, (sys.prefix, root)",
    "assert pathlib.Path(sys.base_prefix).resolve() == root, (sys.base_prefix, root)",
    "modules = {'_ctypes': _ctypes, 'numpy': numpy, 'scipy': scipy, 'manim': manim, 'manim_voiceover': manim_voiceover}",
    "bad = {name: module.__file__ for name, module in modules.items() if not inside(module.__file__)}",
    "assert not bad, bad",
    "outside_site = [p for p in sys.path if p and 'site-packages' in p and not inside(p)]",
    "assert not outside_site, outside_site",
    "print('Bundled runtime OK')",
    "print('executable', sys.executable)",
    "print('prefix', sys.prefix)",
    "print('scipy', scipy.__file__)",
    "print('manim', manim.__file__)",
  ].join("; ");
  runOrThrow(python, ["-c", validationCode], {
    cwd: ROOT_DIR,
    env: bundledPythonEnv(),
  });
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
  copyPythonRuntime(command, prefixArgs);
  patchMacPythonFrameworkLinks();

  const bundledPython = getBundledPythonPath();
  if (!fs.existsSync(bundledPython)) {
    throw new Error(`Bundled runtime python not found at ${bundledPython}.`);
  }

  const pythonOptions = { cwd: ROOT_DIR, env: bundledPythonEnv() };

  // Install every dependency into the copied runtime without consulting user/system packages.
  runOrThrow(bundledPython, ["-m", "ensurepip", "--upgrade"], pythonOptions);
  runOrThrow(
    bundledPython,
    ["-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"],
    pythonOptions
  );
  runOrThrow(
    bundledPython,
    ["-m", "pip", "install", "--no-cache-dir", "-r", REQUIREMENTS_FILE],
    pythonOptions
  );
  // Ensure pkg_resources remains available for manim plugins (manim-voiceover).
  runOrThrow(
    bundledPython,
    ["-m", "pip", "install", "--no-cache-dir", "--upgrade", "setuptools<81"],
    pythonOptions
  );

  // Newly installed native extensions may also reference the build machine's framework.
  patchMacPythonFrameworkLinks();
  validateBundledRuntime(bundledPython);

  // Bundle Playwright Chromium into runtime so end-users do not need manual install.
  runOrThrow(bundledPython, ["-m", "playwright", "install", "chromium"], {
    cwd: ROOT_DIR,
    env: bundledPythonEnv({ PLAYWRIGHT_BROWSERS_PATH: PLAYWRIGHT_BROWSERS_DIR }),
  });
  runOrThrow(bundledPython, ["-m", "manim", "--version"], pythonOptions);

  const ffmpegSource = runAndCaptureOrThrow(
    bundledPython,
    ["-c", "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())"],
    pythonOptions
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
