#!/usr/bin/env node
/*
 * cnipa-integrated-circuit-layout-writer installer.
 * Copies the skill (SKILL.md + references/ + scripts/ + requirements.txt) into an
 * AI agent's skills folder. Default target = Claude Code user skills (~/.claude/skills).
 *
 * Usage:
 *   npx cnipa-integrated-circuit-layout-writer
 *   npx cnipa-integrated-circuit-layout-writer --project
 *   npx cnipa-integrated-circuit-layout-writer --dir <path>
 *   npx cnipa-integrated-circuit-layout-writer --force
 *   npx cnipa-integrated-circuit-layout-writer --dry-run
 *   npx cnipa-integrated-circuit-layout-writer --check
 *
 * Safety: only copies skill files into a skills folder. Never runs pip/apt/brew/winget.
 */
"use strict";
const fs = require("fs");
const os = require("os");
const path = require("path");
const { spawnSync } = require("child_process");

const SKILL_NAME = "cnipa-integrated-circuit-layout-writer";
const ITEMS = ["SKILL.md", "references", "scripts", "requirements.txt", "tests"];
const SRC = path.join(__dirname, "..");

function parseArgs(argv) {
  const a = { force: false, help: false, project: false, dir: null, dryRun: false, check: false, quick: false };
  for (let i = 0; i < argv.length; i++) {
    const v = argv[i];
    if (v === "--force" || v === "-f") a.force = true;
    else if (v === "--help" || v === "-h") a.help = true;
    else if (v === "--project" || v === "-p") a.project = true;
    else if (v === "--dry-run" || v === "-n") a.dryRun = true;
    else if (v === "--check" || v === "doctor") a.check = true;
    else if (v === "--quick") a.quick = true;
    else if (v === "--dir" || v === "-d") a.dir = argv[++i];
    else if (v.startsWith("--dir=")) a.dir = v.slice(6);
  }
  return a;
}

function help() {
  console.log(`Install ${SKILL_NAME} into an agent skills directory.

  npx ${SKILL_NAME} [--project] [--dir PATH] [--force] [--dry-run] [--check] [--quick]
`);
}

function copyDir(src, dest) {
  fs.mkdirSync(dest, { recursive: true });
  for (const ent of fs.readdirSync(src, { withFileTypes: true })) {
    if (ent.name === "__pycache__" || ent.name === ".git") continue;
    const s = path.join(src, ent.name);
    const d = path.join(dest, ent.name);
    if (ent.isDirectory()) copyDir(s, d);
    else fs.copyFileSync(s, d);
  }
}

function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help) { help(); return; }
  let root;
  if (args.dir) root = path.resolve(args.dir);
  else if (args.project) root = path.resolve(".claude", "skills");
  else root = path.join(os.homedir(), ".claude", "skills");
  const dest = path.join(root, SKILL_NAME);
  if (args.check) {
    console.log("target:", dest, fs.existsSync(dest) ? "(exists)" : "(missing)");
    const doctor = path.join(SRC, "scripts", "doctor.py");
    const r = spawnSync("python", [doctor, args.quick ? "--quick" : "--quick"], { stdio: "inherit" });
    process.exit(r.status || 0);
  }
  console.log(args.dryRun ? "[dry-run] would install to" : "install to", dest);
  if (args.dryRun) return;
  if (fs.existsSync(dest) && !args.force) {
    console.error("exists; pass --force to overwrite");
    process.exit(1);
  }
  fs.mkdirSync(dest, { recursive: true });
  for (const item of ITEMS) {
    const s = path.join(SRC, item);
    const d = path.join(dest, item);
    if (!fs.existsSync(s)) continue;
    const st = fs.statSync(s);
    if (st.isDirectory()) copyDir(s, d);
    else fs.copyFileSync(s, d);
  }
  // also copy README/LICENSE/package.json if present
  for (const extra of ["README.md", "LICENSE", "package.json"]) {
    const s = path.join(SRC, extra);
    if (fs.existsSync(s)) fs.copyFileSync(s, path.join(dest, extra));
  }
  console.log("done");
}

main();