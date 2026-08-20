#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");
const { spawnSync } = require("child_process");

const repoRoot = path.resolve(__dirname, "../..");
const runtimeRoot = path.join(repoRoot, "desktop", "python-runtime");

if (process.platform !== "darwin") {
  console.log("[mac-native-audit] skipped: not running on macOS");
  process.exit(0);
}

function run(command, args) {
  return spawnSync(command, args, {
    encoding: "utf8",
    maxBuffer: 32 * 1024 * 1024,
  });
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
  const inPythonBin = file.startsWith(
    path.join(runtimeRoot, "python", "bin") + path.sep
  );
  const inNativeLibs = file.startsWith(
    path.join(runtimeRoot, "native-libs") + path.sep
  );

  const likely =
    base === "Python" ||
    inPythonBin ||
    inNativeLibs ||
    /\.(so|dylib|bundle)$/i.test(base);

  if (!likely) return false;

  const result = run("/usr/bin/file", ["-b", file]);
  return result.status === 0 && /Mach-O/.test(result.stdout || "");
}

function parseLoadCommands(file) {
  const result = run("/usr/bin/otool", ["-l", file]);
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

  const seen = new Set();
  return records.filter((record) => {
    const key = `${record.kind}\0${record.value}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function allowedAbsolute(value) {
  return (
    value.startsWith("/usr/lib/") ||
    value === "/usr/lib/libSystem.B.dylib" ||
    value.startsWith("/System/Library/")
  );
}

function isPortable(value) {
  if (
    value.startsWith("@rpath/") ||
    value.startsWith("@loader_path/") ||
    value.startsWith("@executable_path/")
  ) {
    return true;
  }
  if (!value.startsWith("/")) return true;
  return allowedAbsolute(value);
}

const files = walk(runtimeRoot).filter(isRuntimeMachO);
const failures = [];

for (const file of files) {
  for (const record of parseLoadCommands(file)) {
    if (!isPortable(record.value)) {
      failures.push({ file, ...record });
    }
  }
}

console.log(
  `[mac-native-audit] scanned ${files.length} runtime Mach-O files under ${runtimeRoot}`
);

if (failures.length === 0) {
  console.log(
    "[mac-native-audit] OK: no non-portable runtime dylib/rpath references found"
  );
  process.exit(0);
}

console.error(
  `[mac-native-audit] FAILED: found ${failures.length} non-portable runtime reference(s)`
);

for (const failure of failures) {
  console.error(`\n${path.relative(repoRoot, failure.file)}`);
  console.error(`  ${failure.cmd}: ${failure.value}`);
}

process.exit(1);
