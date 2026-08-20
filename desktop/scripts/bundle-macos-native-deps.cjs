#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");
const { spawnSync } = require("child_process");

const repoRoot = path.resolve(__dirname, "../..");
const runtimeRoot = path.join(repoRoot, "desktop", "python-runtime");
const pythonRoot = path.join(runtimeRoot, "python");
const nativeLibRoot = path.join(runtimeRoot, "native-libs");

const OTOOL = "/usr/bin/otool";
const INSTALL_NAME_TOOL = "/usr/bin/install_name_tool";
const CODESIGN = "/usr/bin/codesign";
const FILE = "/usr/bin/file";

if (process.platform !== "darwin") {
  console.log("[mac-native-bundle] skipped: not running on macOS");
  process.exit(0);
}

for (const required of [OTOOL, INSTALL_NAME_TOOL, CODESIGN, FILE]) {
  if (!fs.existsSync(required)) {
    throw new Error(`[mac-native-bundle] required macOS tool is missing: ${required}`);
  }
}

function run(command, args, options = {}) {
  return spawnSync(command, args, {
    encoding: "utf8",
    maxBuffer: 32 * 1024 * 1024,
    ...options,
  });
}

function runOrThrow(command, args) {
  const result = run(command, args);
  if (result.status !== 0) {
    const details = [
      `status=${result.status}`,
      result.signal ? `signal=${result.signal}` : null,
      result.error ? `error=${result.error.message}` : null,
      String(result.stderr || "").trim() || null,
    ]
      .filter(Boolean)
      .join("\n");
    throw new Error(
      `[mac-native-bundle] command failed:\n${command} ${args.join(" ")}\n${details}`
    );
  }
  return String(result.stdout || "");
}

function walk(dir, out = []) {
  if (!fs.existsSync(dir)) return out;
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (entry.name.endsWith(".dSYM")) continue;
      walk(full, out);
    } else if (entry.isFile() || entry.isSymbolicLink()) {
      out.push(full);
    }
  }
  return out;
}

function isRuntimeMachO(file) {
  if (file.includes(`${path.sep}.dSYM${path.sep}`)) return false;
  if (/\.(a|o)$/i.test(file)) return false;

  const base = path.basename(file);
  const inBin = file.startsWith(path.join(pythonRoot, "bin") + path.sep);
  const likely =
    base === "Python" ||
    inBin ||
    /\.(so|dylib|bundle)$/i.test(base);

  if (!likely) return false;

  const result = run(FILE, ["-b", file]);
  return result.status === 0 && /Mach-O/.test(String(result.stdout || ""));
}

function parseLoadCommands(file) {
  const result = run(OTOOL, ["-l", file]);
  if (result.status !== 0) return [];

  const lines = String(result.stdout || "").split(/\r?\n/);
  const records = [];
  let currentCmd = null;

  for (const raw of lines) {
    const line = raw.trim();
    const cmdMatch = line.match(/^cmd (LC_[A-Z0-9_]+)$/);
    if (cmdMatch) {
      currentCmd = cmdMatch[1];
      continue;
    }

    if (!currentCmd) continue;

    if (currentCmd === "LC_RPATH") {
      const match = line.match(/^path (.+?) \(offset \d+\)$/);
      if (match) {
        records.push({ kind: "rpath", cmd: currentCmd, value: match[1] });
        currentCmd = null;
      }
      continue;
    }

    if (
      currentCmd === "LC_LOAD_DYLIB" ||
      currentCmd === "LC_LOAD_WEAK_DYLIB" ||
      currentCmd === "LC_REEXPORT_DYLIB" ||
      currentCmd === "LC_LOAD_UPWARD_DYLIB" ||
      currentCmd === "LC_LAZY_LOAD_DYLIB"
    ) {
      const match = line.match(/^name (.+?) \(offset \d+\)$/);
      if (match) {
        records.push({ kind: "dependency", cmd: currentCmd, value: match[1] });
        currentCmd = null;
      }
    }
  }

  // Universal binaries can make otool print the same load command once per slice.
  const seen = new Set();
  return records.filter((record) => {
    const key = `${record.kind}\0${record.value}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function isAppleSystemPath(value) {
  return (
    value.startsWith("/usr/lib/") ||
    value === "/usr/lib/libSystem.B.dylib" ||
    value.startsWith("/System/Library/")
  );
}

function isPortableReference(value) {
  return (
    value.startsWith("@rpath/") ||
    value.startsWith("@loader_path/") ||
    value.startsWith("@executable_path/") ||
    isAppleSystemPath(value)
  );
}

function frameworkTargetFor(value) {
  const match = value.match(
    /^\/Library\/Frameworks\/Python\.framework\/Versions\/[^/]+\/(.+)$/
  );
  if (!match) return null;
  return path.join(pythonRoot, match[1]);
}

function relativeLoaderReference(fromFile, toFile) {
  let rel = path.relative(path.dirname(fromFile), toFile);
  if (!rel.startsWith(".")) rel = `./${rel}`;
  return `@loader_path/${rel}`;
}

function sign(file) {
  runOrThrow(CODESIGN, ["--force", "--sign", "-", file]);
}

function removeBadRpath(file, rpath) {
  runOrThrow(INSTALL_NAME_TOOL, ["-delete_rpath", rpath, file]);
}

function rewriteDependency(file, oldValue, targetFile) {
  if (!fs.existsSync(targetFile)) {
    throw new Error(
      `[mac-native-bundle] target for ${oldValue} does not exist:\n${targetFile}\n` +
        `while processing ${file}`
    );
  }

  const replacement = relativeLoaderReference(file, targetFile);
  runOrThrow(INSTALL_NAME_TOOL, ["-change", oldValue, replacement, file]);
  return replacement;
}

fs.mkdirSync(nativeLibRoot, { recursive: true });

const externalCopies = new Map(); // canonical source -> bundled target
const targetOwners = new Map(); // bundled target -> canonical source
const queued = new Set();
const queue = [];
const modified = new Set();
let copiedCount = 0;
let rewrittenCount = 0;
let removedRpathCount = 0;

function enqueue(file) {
  const resolved = path.resolve(file);
  if (queued.has(resolved)) return;
  if (!isRuntimeMachO(resolved)) return;
  queued.add(resolved);
  queue.push(resolved);
}

function copyExternalDependency(sourcePath) {
  if (!fs.existsSync(sourcePath)) {
    throw new Error(
      `[mac-native-bundle] non-system dylib is missing on the build machine:\n${sourcePath}`
    );
  }

  const canonical = fs.realpathSync(sourcePath);
  if (externalCopies.has(canonical)) return externalCopies.get(canonical);

  const target = path.join(nativeLibRoot, path.basename(sourcePath));
  const existingOwner = targetOwners.get(target);
  if (existingOwner && existingOwner !== canonical) {
    throw new Error(
      `[mac-native-bundle] dylib filename collision for ${path.basename(target)}:\n` +
        `  ${existingOwner}\n  ${canonical}`
    );
  }

  fs.copyFileSync(canonical, target);
  try {
    fs.chmodSync(target, 0o755);
  } catch {}

  externalCopies.set(canonical, target);
  targetOwners.set(target, canonical);
  copiedCount += 1;
  enqueue(target);

  console.log(
    `[mac-native-bundle] copied ${sourcePath} -> ${path.relative(repoRoot, target)}`
  );

  return target;
}

for (const file of walk(pythonRoot)) enqueue(file);

while (queue.length > 0) {
  const file = queue.shift();
  const records = parseLoadCommands(file);
  let changed = false;

  for (const record of records) {
    if (record.kind === "rpath") {
      if (record.value.startsWith("/") && !isAppleSystemPath(record.value)) {
        removeBadRpath(file, record.value);
        removedRpathCount += 1;
        changed = true;
        console.log(
          `[mac-native-bundle] removed rpath ${record.value} from ${path.relative(repoRoot, file)}`
        );
      }
      continue;
    }

    const dep = record.value;
    if (isPortableReference(dep) || !dep.startsWith("/")) continue;

    const frameworkTarget = frameworkTargetFor(dep);
    let target;

    if (frameworkTarget) {
      target = frameworkTarget;
    } else {
      target = copyExternalDependency(dep);
    }

    const replacement = rewriteDependency(file, dep, target);
    rewrittenCount += 1;
    changed = true;

    console.log(
      `[mac-native-bundle] rewrote ${path.relative(repoRoot, file)}\n` +
        `  ${dep}\n  -> ${replacement}`
    );
  }

  if (changed) modified.add(file);
}

// Copied dylibs may have been discovered after their importers. Process until stable.
let discoveredMore = true;
while (discoveredMore) {
  discoveredMore = false;
  for (const file of walk(nativeLibRoot)) {
    const before = queued.size;
    enqueue(file);
    if (queued.size > before) discoveredMore = true;
  }
  while (queue.length > 0) {
    const file = queue.shift();
    const records = parseLoadCommands(file);
    let changed = false;

    for (const record of records) {
      if (record.kind === "rpath") {
        if (record.value.startsWith("/") && !isAppleSystemPath(record.value)) {
          removeBadRpath(file, record.value);
          removedRpathCount += 1;
          changed = true;
        }
        continue;
      }

      const dep = record.value;
      if (isPortableReference(dep) || !dep.startsWith("/")) continue;

      const frameworkTarget = frameworkTargetFor(dep);
      const target = frameworkTarget || copyExternalDependency(dep);
      rewriteDependency(file, dep, target);
      rewrittenCount += 1;
      changed = true;
    }

    if (changed) modified.add(file);
  }
}

// install_name_tool invalidates signatures. Sign only after all edits are complete.
for (const file of modified) sign(file);

console.log(
  `[mac-native-bundle] ready: copied ${copiedCount} external dylib(s), ` +
    `rewrote ${rewrittenCount} dependency reference(s), removed ${removedRpathCount} ` +
    `non-portable rpath(s), ad-hoc signed ${modified.size} modified Mach-O file(s)`
);
