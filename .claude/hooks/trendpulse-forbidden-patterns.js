#!/usr/bin/env node
// trendpulse-forbidden-patterns — PostToolUse(Edit|Write): non-blocking conventions warn
//  Flags high-signal Python anti-patterns in the project's *.py sources:
//  bare `except:` / `except Exception: pass`, `# type: ignore`, `: Any` / `-> Any`.
const fs = require('fs');

let input = '';
try { input = fs.readFileSync(0, 'utf8'); } catch {}
let data = {};
try { data = JSON.parse(input); } catch {}
const ti = data.tool_input || {};
const fp = ti.file_path || '';

// Only Python sources, skip tests + virtualenvs
if (!/\.py$/.test(fp)) process.exit(0);
if (/(^|\/)(\.venv|venv|site-packages|node_modules)\//.test(fp)) process.exit(0);

let text = ti.content || ti.new_string || '';
if (!text) { try { text = fs.readFileSync(fp, 'utf8'); } catch {} }

const hits = [];
if (/:\s*Any\b/.test(text) || /->\s*Any\b/.test(text)) hits.push('Any type hint');
if (/#\s*type:\s*ignore/.test(text)) hits.push('# type: ignore');
if (/except\s*:/.test(text)) hits.push('bare except:');
if (/except\s+Exception\s*:\s*\n\s*pass\b/.test(text) || /except[^\n]*:\s*pass\b/.test(text)) hits.push('except …: pass (swallowed error)');

if (hits.length) {
  const name = fp.split('/').slice(-1)[0];
  const msg = '⚠️ trendpulse conventions: ' + name + ' — найдено: ' + hits.join(', ')
    + '. Запрещено (CONVENTIONS.md): no bare `Any`, no `# type: ignore`, no swallowed exceptions — типизируй и обрабатывай ошибки явно.';
  // non-blocking: feed back as context + stderr; exit 0 so the edit is not reverted
  try { process.stdout.write(JSON.stringify({ hookSpecificOutput: { hookEventName: 'PostToolUse', additionalContext: msg } })); } catch {}
  process.stderr.write(msg + '\n');
}

process.exit(0);
