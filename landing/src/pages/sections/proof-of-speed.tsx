import { useCases } from '@/shared/cases/cases-context';
import type { CaseItem } from '@/shared/cases/types';

/**
 * TASK-067: live proof-of-speed cases from GET /api/v1/cases (SSR-fetched).
 * Renders ONLY when there are at least MIN_CASES_TO_SHOW cases — fewer looks
 * like an empty showcase, so the section silently disappears from the DOM.
 * `channels_count` is deliberately not shown (MVP = 1 would weaken the proof).
 */
const MIN_CASES_TO_SHOW = 3;

const SECONDS_PER_MINUTE = 60;
const SECONDS_PER_HOUR = 3600;

function formatUtcTime(isoTimestamp: string): string {
  const date = new Date(isoTimestamp);
  if (Number.isNaN(date.getTime())) return '—';
  return date.toISOString().slice(11, 16);
}

function formatLeadTime(leadTimeSeconds: number): string {
  if (leadTimeSeconds < SECONDS_PER_MINUTE) return '<1 min';
  if (leadTimeSeconds < SECONDS_PER_HOUR) {
    return `${Math.floor(leadTimeSeconds / SECONDS_PER_MINUTE)} min`;
  }
  const hours = Math.floor(leadTimeSeconds / SECONDS_PER_HOUR);
  const minutes = Math.floor((leadTimeSeconds % SECONDS_PER_HOUR) / SECONDS_PER_MINUTE);
  return minutes > 0 ? `${hours} h ${minutes} min` : `${hours} h`;
}

function CaseCard({ caseItem }: { caseItem: CaseItem }) {
  return (
    <div className="bg-card border border-border rounded-xl p-5 shadow-sm font-mono text-sm text-left">
      <p className="text-foreground leading-relaxed">
        <span className="text-primary">&quot;{caseItem.title}&quot;</span>
      </p>
      <p className="text-muted-foreground mt-2">
        detected <strong className="text-foreground">{formatUtcTime(caseItem.first_seen)}</strong>
        {' → '}
        mainstream <strong className="text-foreground">{formatUtcTime(caseItem.mainstream_at)}</strong>
        <span className="text-xs"> UTC</span>
      </p>
      <p className="text-muted-foreground mt-1">
        <strong className="text-foreground">{formatLeadTime(caseItem.lead_time_seconds)}</strong> ahead
        &nbsp;·&nbsp; Score: <strong className="text-foreground">{Math.round(caseItem.viral_score)}</strong>
      </p>
    </div>
  );
}

export function ProofOfSpeedSection() {
  const cases = useCases();

  if (cases.length < MIN_CASES_TO_SHOW) return null;

  return (
    <section id="proof-of-speed" className="py-16 px-6 lg:px-20 snap-start scroll-mt-16">
      <div className="max-w-6xl mx-auto">
        <div className="text-center mb-10">
          <h2 className="text-3xl md:text-4xl font-bold mb-4 tracking-tight">Proof of speed</h2>
          <p className="text-lg text-muted-foreground max-w-2xl mx-auto">
            Real detections: spotted in public Telegram channels before they hit mainstream media.
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {cases.map((caseItem) => (
            <CaseCard key={`${caseItem.title}-${caseItem.first_seen}`} caseItem={caseItem} />
          ))}
        </div>

        <p className="text-xs text-muted-foreground text-center mt-6">
          Times in UTC. Only public channels monitored — raw content discarded after 48 h.
        </p>
      </div>
    </section>
  );
}
