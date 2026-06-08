#!/usr/bin/env node
// trendpulse-bash-guard — PreToolUse(Bash): enforce project rules
//  • no push/commit to main/master  • Conventional Commits
const fs = require('fs');

let input = '';
try { input = fs.readFileSync(0, 'utf8'); } catch {}
let cmd = '';
try { cmd = ((JSON.parse(input).tool_input) || {}).command || ''; } catch {}

function block(msg) {
  process.stderr.write('⛔ trendpulse: ' + msg + '\n');
  process.exit(2); // exit 2 → blocks the tool call, stderr shown to the model
}

if (!cmd) process.exit(0);

// 1. push to main/master
if (/\bgit\s+push\b/.test(cmd) && /\b(main|master)\b/.test(cmd)) {
  block('push в main/master запрещён — работаем через ветки gsd/phase-* и PR.');
}

// 2. Conventional Commits on -m message
const m = cmd.match(/git\s+commit\b[^|&;]*?-m\s+(['"])([\s\S]*?)\1/);
if (m) {
  const msg = m[2];
  if (!/^(feat|fix|refactor|docs|test|chore|perf|ci)(\([^)]+\))?!?:\s/.test(msg)) {
    block('commit не по Conventional Commits: "' + msg.slice(0, 60) + '". Формат: feat|fix|refactor|docs|test|chore|perf|ci: …');
  }
}

// 3. commit while on main/master (best-effort; honors `cd <dir> &&` prefix)
if (/\bgit\s+commit\b/.test(cmd)) {
  const { execSync } = require('child_process');
  let dir = process.env.CLAUDE_PROJECT_DIR || process.cwd();
  const cdm = cmd.match(/cd\s+([^\s;&|]+)\s*&&/);
  if (cdm) dir = cdm[1].replace(/^["']|["']$/g, '');
  try {
    const br = execSync('git -C "' + dir + '" rev-parse --abbrev-ref HEAD', { stdio: ['ignore', 'pipe', 'ignore'] }).toString().trim();
    if (br === 'main' || br === 'master') block('commit напрямую в ' + br + ' запрещён — создай ветку gsd/phase-*.');
  } catch { /* not a git repo / unknown branch → allow */ }
}

process.exit(0);
