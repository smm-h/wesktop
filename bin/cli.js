#!/usr/bin/env node
"use strict";

const { execFileSync, spawnSync } = require("child_process");

try {
  execFileSync("python3", ["--version"], { stdio: "pipe" });
} catch {
  console.error("webpane requires Python 3.11+. Install from https://python.org/");
  process.exit(1);
}

const result = spawnSync("python3", ["-m", "webpane", ...process.argv.slice(2)], {
  stdio: "inherit",
});
process.exit(result.status ?? 1);
