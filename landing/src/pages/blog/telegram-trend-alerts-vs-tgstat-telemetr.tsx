import { Link } from '@tanstack/react-router';
import { SITE } from '@/shared/site/constants';
import { BLOG_ARTICLES } from '@/shared/blog/articles';
import { BlogArticleLayout } from './blog-article-layout';

const meta = BLOG_ARTICLES.find((a) => a.slug === 'telegram-trend-alerts-vs-tgstat-telemetr');

const COMPETITOR_FACTS_CHECKED_ON = 'June 11, 2026';

/**
 * TASK-073, article 2 (honest comparison). Hard rules from the task doc:
 * no false or belittling claims about competitors — only facts verifiable on
 * their public websites, with the check date stated in the text; no claims
 * about our own product beyond what is shipped (overview.md §6).
 */
export function TelegramTrendAlertsVsTgstatTelemetrPage() {
  if (!meta) return null;

  return (
    <BlogArticleLayout meta={meta}>
      <p>
        &ldquo;Which Telegram analytics tool should I use?&rdquo; is usually the wrong question —
        TGStat, Telemetr and {SITE.brandName} are built for different jobs. This is an honest
        comparison of what each one actually does, so you can pick the right tool (sometimes the
        right answer is more than one). Facts about TGStat and Telemetr below were checked against
        their public websites on {COMPETITOR_FACTS_CHECKED_ON}.
      </p>

      <h2>What TGStat and Telemetr are for</h2>
      <p>
        TGStat and Telemetr are mature, well-established <strong>channel analytics</strong>{' '}
        platforms. Their core is a large catalog of Telegram channels with statistics: subscriber
        counts and growth history, view counts, citation and mention tracking, ratings by category
        and language, and tooling around the channel advertising market. If your question is
        &ldquo;how big is this channel, how fast is it growing, and is it worth buying an ad
        in?&rdquo;, they are the standard answers, and they are good at it.
      </p>
      <p>
        Both are primarily <strong>research tools</strong>: you open them, search, and study a
        channel or a niche. That workflow is exactly right for ad buying, competitor research and
        audience audits.
      </p>

      <h2>What {SITE.brandName} is for</h2>
      <p>
        {SITE.brandName} answers a different question: <strong>&ldquo;what is going viral right
        now?&rdquo;</strong> It is alert-first, not catalog-first. You define a watchlist of public
        channels and a topic; the system clusters similar posts across channels in real time,
        scores how fast each story spreads, and pushes an alert (Telegram bot or webhook) the
        moment a story starts breaking out — with a first-seen timestamp, so the lead time over
        mainstream pickup is measurable for every detection.
      </p>
      <p>
        There is no big public channel catalog, no audience demographics, no ad-market tooling —
        and that is deliberate. The product is the early signal, not the encyclopedia.
      </p>

      <h2>Side by side</h2>
      <ul>
        <li>
          <strong>Primary job.</strong> TGStat / Telemetr: channel statistics, ratings and
          ad-market research. {SITE.brandName}: real-time detection of stories that are starting
          to spread.
        </li>
        <li>
          <strong>Workflow.</strong> They are pull — you go and look things up. {SITE.brandName} is
          push — alerts come to you when something crosses your threshold.
        </li>
        <li>
          <strong>Unit of analysis.</strong> They are centered on the <em>channel</em>.{' '}
          {SITE.brandName} is centered on the <em>story</em> — one cluster across many channels.
        </li>
        <li>
          <strong>History.</strong> They maintain long multi-year channel statistics.{' '}
          {SITE.brandName} keeps trend history on paid plans only (30 or 90 days) and discards raw
          post content after {SITE.compliance.dataRetentionHours} hours by design.
        </li>
        <li>
          <strong>Payments.</strong> {SITE.brandName} is paid in cryptocurrency (via{' '}
          {SITE.pricing.paymentProcessor}); see{' '}
          <Link to="/pricing" className="text-primary hover:underline">
            pricing
          </Link>{' '}
          for current plans.
        </li>
      </ul>

      <h2>When to use which</h2>
      <ul>
        <li>
          <strong>Buying or selling channel ads, auditing audiences:</strong> TGStat or Telemetr.
        </li>
        <li>
          <strong>Trading on news, running a fast media channel, tracking a narrative:</strong>{' '}
          {SITE.brandName}.
        </li>
        <li>
          <strong>Both jobs:</strong> use both — research the niche in a catalog, then put its best
          channels into a {SITE.brandName} watchlist and let the alerts do the watching.
        </li>
      </ul>

      <p>
        The honest bottom line: if you need channel analytics, the established catalogs are
        excellent and we are not trying to replace them. If you need to know about a breaking story
        before it is everywhere, that single job is what {SITE.brandName} is built for — you can{' '}
        <Link to="/pricing" className="text-primary hover:underline">
          start on the free plan
        </Link>{' '}
        and judge the lead time yourself.
      </p>
    </BlogArticleLayout>
  );
}
