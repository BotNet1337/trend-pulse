import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

type Finding = {
  file: string;
  line: number;
  match: string;
  ruleId: string;
};

async function listFilesRecursive(dir: string): Promise<string[]> {
  const entries = await fs.readdir(dir, { withFileTypes: true });
  const files: string[] = [];
  for (const e of entries) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) {
      files.push(...(await listFilesRecursive(p)));
    } else {
      files.push(p);
    }
  }
  return files;
}

function findInText(args: {
  filePath: string;
  relFilePath: string;
  text: string;
  rules: { id: string; re: RegExp }[];
}): Finding[] {
  const out: Finding[] = [];
  const lines = args.text.split('\n');
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i] ?? '';
    for (const rule of args.rules) {
      rule.re.lastIndex = 0;
      const m = rule.re.exec(line);
      if (!m) continue;
      out.push({
        file: args.relFilePath,
        line: i + 1,
        match: (m[0] ?? '').trim(),
        ruleId: rule.id,
      });
    }
  }
  return out;
}

async function main() {
  const repoRoot = path.resolve(__dirname, '..');
  const srcRoot = path.resolve(repoRoot, 'src');
  const pagesRoot = path.resolve(srcRoot, 'pages');
  const sharedRoot = path.resolve(srcRoot, 'shared');

  const rules: { id: string; re: RegExp }[] = [
    // hard guarantees / risky marketing claims
    { id: 'hard_guarantee', re: /\b(99\.9%|SLA|money-back|money back|guarantee|grandfathered)\b/i },
    // security over-claims
    { id: 'security_overclaim', re: /\b(bank-level|enterprise-grade|SOC\s*2|24\/7|penetration test|WAF)\b/i },
    { id: 'security_specific_crypto', re: /\b(AES-256|TLS\s*1\.3)\b/i },
    // “all models” over-claim (models change)
    { id: 'all_models_claim', re: /\ball models\b/i },
    // items to avoid as differentiators in landing marketing copy
    { id: 'billing_uploads_as_feature', re: /\b(file uploads?|credits billing|Stripe billing)\b/i },
    // stale specificity that tends to drift
    { id: 'model_specificity', re: /\b(GPT-4 Turbo)\b/i },
  ];

  const candidateFiles = [
    ...(await listFilesRecursive(pagesRoot)),
    ...(await listFilesRecursive(sharedRoot)),
  ]
    .filter((p) => p.endsWith('.ts') || p.endsWith('.tsx'))
    .filter((p) => !p.includes(`${path.sep}node_modules${path.sep}`));

  const findings: Finding[] = [];
  for (const filePath of candidateFiles) {
    const rel = path.relative(repoRoot, filePath);
    const text = await fs.readFile(filePath, 'utf8');
    findings.push(...findInText({ filePath, relFilePath: rel, text, rules }));
  }

  console.log(`[audit:copy] scanned_files=${candidateFiles.length}`);

  if (findings.length === 0) {
    console.log('[audit:copy] ok (no findings)');
    return;
  }

  console.error(`[audit:copy] findings=${findings.length}`);
  for (const f of findings) {
    console.error(`- ${f.file}:${f.line} [${f.ruleId}] ${f.match}`);
  }

  process.exitCode = 1;
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});


