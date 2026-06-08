#!/usr/bin/env node
// trendpulse-learnings-guard — Stop: non-blocking reminder if ship done but learnings not captured
const fs = require('fs');
const path = require('path');

const root = process.env.CLAUDE_PROJECT_DIR || process.cwd();
const tasksDir = path.join(root, 'docs', 'tasks');
const pending = [];

try {
  for (const f of fs.readdirSync(tasksDir)) {
    if (!/^task-.*\.md$/.test(f)) continue;
    const t = fs.readFileSync(path.join(tasksDir, f), 'utf8');
    if (/- \[x\] 6 ship/.test(t) && /- \[ \] 7 learnings/.test(t)) pending.push(f);
  }
} catch { /* no tasks dir */ }

if (pending.length) {
  process.stderr.write('📝 trendpulse: ship выполнен, но learnings не дописаны для: '
    + pending.join(', ') + '. Допиши в docs/learnings.md (стадия 7) + memory/ADR для долгоживущего.\n');
}
process.exit(0);
