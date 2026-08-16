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
  rewriteSymlinksIntoCopy(basePrefix);
  removeExternallyManagedMarkers();
  return basePrefix;
}

// `dereference: true` does not flatten every link: cpSync leaves nested symlinks as symlinks and
// rewrites their targets to absolute paths, so a copied `bin/python3` can still point at the
// interpreter it was copied FROM. That ships a link into a path no end user has, and it makes
// `Path(sys.executable).resolve()` escape the bundle -- which is what validateBundledRuntime's
// prefix assertions are there to catch. Repoint such links at the equivalent file inside the copy,
// relatively, which is how a normal Python install expresses them.
//
// Linux-only, matching removeExternallyManagedMarkers: the mac and Windows bundles are built from
// interpreters whose internal links are already relative, so this finds nothing to rewrite there.
function rewriteSymlinksIntoCopy(basePrefix) {
  if (process.platform !== "linux") return;

  const base = path.resolve(basePrefix);
  const stack = [PYTHON_DIR];
  while (stack.length) {
    const current = stack.pop();
    for (const entry of fs.readdirSync(current, { withFileTypes: true })) {
      const fullPath = path.join(current, entry.name);
      if (entry.isSymbolicLink()) {
        const target = fs.readlinkSync(fullPath);
        if (!path.isAbsolute(target)) continue;
        const resolved = path.resolve(target);
        const insideBase = resolved === base || resolved.startsWith(base + path.sep);
        if (!insideBase) continue;

        const counterpart = path.join(PYTHON_DIR, path.relative(base, resolved));
        if (!fs.existsSync(counterpart)) continue;
        const relative = path.relative(path.dirname(fullPath), counterpart);
        fs.rmSync(fullPath, { force: true });
        fs.symlinkSync(relative, fullPath);
        console.log(`[desktop] repointed bundled symlink into the copy: ${fullPath} -> ${relative}`);
        continue;
      }
      if (entry.isDirectory()) stack.push(fullPath);
    }
  }
}

// PEP 668 marker files travel with the copy when the base interpreter is managed by a distro
// or by uv, and they make `ensurepip`/`pip install` refuse to touch the runtime. The copy is a
// private bundle that nothing else shares, so the marker has no meaning here -- dropping it is
// the correct scope, unlike --break-system-packages which would also apply to the base install.
//
// Deliberately Linux-only: the mac and Windows bundles are built from interpreters that ship no
// marker, so this is a no-op there and is scoped out to keep those paths byte-identical. A mac
// bundle built from Homebrew's python@3.12 would carry a marker and fail at ensurepip; widen the
// guard rather than reaching for pip's --break-system-packages if that ever comes up.
function removeExternallyManagedMarkers() {
  if (process.platform !== "linux") return;

  const libDir = path.join(PYTHON_DIR, "lib");
  if (!fs.existsSync(libDir)) return;

  const candidates = [path.join(PYTHON_DIR, "EXTERNALLY-MANAGED")];
  for (const entry of fs.readdirSync(libDir, { withFileTypes: true })) {
    if (entry.isDirectory() && entry.name.startsWith("python")) {
      candidates.push(path.join(libDir, entry.name, "EXTERNALLY-MANAGED"));
    }
  }

  for (const candidate of candidates) {
    if (fs.existsSync(candidate)) {
      fs.rmSync(candidate, { force: true });
      console.log(`[desktop] removed PEP 668 marker from bundled runtime: ${candidate}`);
    }
  }
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
    "import cairo, numpy, scipy, manim, manim_voiceover",
    "from manim_voiceover.services.gtts import GTTSService",
    "import edge_tts",
    "surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1)",
    "tee = cairo.TeeSurface(surface)",
    "tee.index(0)",
    "root = pathlib.Path(sys.executable).resolve().parent if sys.platform == 'win32' else pathlib.Path(sys.executable).resolve().parents[1]",
    "inside = lambda value: pathlib.Path(value).resolve() == root or root in pathlib.Path(value).resolve().parents",
    "assert pathlib.Path(sys.prefix).resolve() == root, (sys.prefix, root)",
    "assert pathlib.Path(sys.base_prefix).resolve() == root, (sys.base_prefix, root)",
    "modules = {'_ctypes': _ctypes, 'cairo': cairo, 'numpy': numpy, 'scipy': scipy, 'manim': manim, 'manim_voiceover': manim_voiceover}",
    // Statically linked extensions have no __file__ (python-build-standalone compiles _ctypes into
    // the interpreter). Those cannot come from outside the bundle, but prove they really are
    // built in rather than letting a missing __file__ excuse a module that escaped the runtime.
    "located = {name: getattr(module, '__file__', None) for name, module in modules.items()}",
    "embedded = sorted(name for name, value in located.items() if value is None)",
    "assert all(name in sys.builtin_module_names for name in embedded), embedded",
    "bad = {name: value for name, value in located.items() if value and not inside(value)}",
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
