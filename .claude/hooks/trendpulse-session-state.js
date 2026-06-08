#!/usr/bin/env node
// trendpulse-session-state — SessionStart: inject unfinished task state (resume context)
const fs = require('fs');
const path = require('path');

const root = process.env.CLAUDE_PROJECT_DIR || process.cwd();
const tasksDir = path.join(root, 'docs', 'tasks');
const out = [];

try {
  for (const f of fs.readdirSync(tasksDir)) {
    if (!/^task-.*\.md$/.test(f)) continue;
    const t = fs.readFileSync(path.join(tasksDir, f), 'utf8');
    if (!/status:\s*in-progress/.test(t)) continue;
    const cs = (t.match(/current_step:\s*(\S+)/) || [])[1];
    const next = (t.match(/- \[ \] \d[^\n]*/g) || []).slice(0, 2).map((s) => s.trim().replace(/^- \[ \]\s*/, ''));
    out.push('• ' + f + (cs ? ` (current_step: ${cs})` : '') + (next.length ? ` — next: ${next.join('; ')}` : ''));
  }
} catch { /* no tasks dir */ }

if (out.length) {
  console.log('🔧 TrendPulse — незавершённые операции trendpulse-executor:\n' + out.join('\n')
    + '\n→ используй trendpulse-resume, чтобы продолжить с current_step.');
}

// nudge to distill learnings → memory when unpromoted ledger entries pile up
try {
  const ledger = fs.readFileSync(path.join(root, 'docs', 'learnings.md'), 'utf8');
  const blocks = (ledger.match(/^## \d{4}-\d{2}-\d{2}/gm) || []).length;
  const promoted = (ledger.match(/<!--\s*promoted/g) || []).length;
  const unpromoted = Math.max(0, blocks - promoted);
  if (unpromoted >= 5) {
    console.log(`📚 TrendPulse — ${unpromoted} непромоутнутых уроков в docs/learnings.md.\n→ запусти trendpulse-distill-learnings, чтобы перенести их в memory.`);
  }
} catch { /* no ledger yet */ }

process.exit(0);
