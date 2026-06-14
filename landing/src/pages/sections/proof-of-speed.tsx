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
    <article className="fs-glass fs-card-hover p-6 text-left">
      <h3 className="mb-2.5 text-base font-semibold text-[color:var(--aurora-cyan-bright)]">
        &quot;{caseItem.title}&quot;
      </h3>
      <p className="mb-3 text-sm tabular-nums text-muted-foreground">
        detected <strong className="text-foreground">{formatUtcTime(caseItem.first_seen)}</strong>
        {' → '}
        mainstream <strong className="text-foreground">{formatUtcTime(caseItem.mainstream_at)}</strong>
        <span className="text-xs"> UTC</span>
      </p>
      <p className="m-0 inline-flex items-baseline gap-1.5 font-bold">
        <span className="fs-grad-text text-2xl tracking-[-0.02em]">{formatLeadTime(caseItem.lead_time_seconds)}</span>
        <span className="text-sm font-medium text-muted-foreground">
          ahead &nbsp;·&nbsp; Score: {Math.round(caseItem.viral_score)}
        </span>
      </p>
    </article>
  );
}

export function ProofOfSpeedSection() {
  const cases = useCases();

  if (cases.length < MIN_CASES_TO_SHOW) return null;

  return (
    <section id="proof-of-speed" className="py-20 md:py-24 px-6 lg:px-20 snap-start scroll-mt-16">
      <div className="max-w-6xl mx-auto">
        <div className="text-center max-w-2xl mx-auto mb-12">
          <h2 className="text-3xl md:text-4xl font-bold mb-4 tracking-tight">Proof of speed</h2>
          <p className="text-lg text-muted-foreground">
            Real detections: spotted in public Telegram channels before they hit mainstream media.
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
          {cases.map((caseItem) => (
            <CaseCard key={`${caseItem.title}-${caseItem.first_seen}`} caseItem={caseItem} />
          ))}
        </div>

        <p className="text-sm text-[color:var(--aurora-text-faint)] text-center mt-7">
          Times in UTC. Only public channels monitored — raw content discarded after 48 h.
        </p>
      </div>
    </section>
  );
}
