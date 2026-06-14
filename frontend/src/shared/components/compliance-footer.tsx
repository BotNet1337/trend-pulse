import * as React from 'react'

import { SUPPORT_EMAIL } from '@/shared/config'

/**
 * Compliance footer — slim legal/compliance bar shown on every app and auth
 * page, ported from designs/trendPulse/variants/app (`.fs-appfooter`). Content
 * (copyright, retention notice, legal links) is verbatim from the design.
 */
export const ComplianceFooter: React.FC = () => {
  return (
    <footer className="fs-appfooter">
      <div className="fs-container fs-appfooter__inner">
        <p className="fs-appfooter__meta">
          &copy; 2026 Foresignal &middot; Public Telegram channels only &middot; 48-hour content
          retention
        </p>
        <ul className="fs-appfooter__links">
          <li>
            <a href="https://foresignal.biz/privacy-policy">Privacy Policy</a>
          </li>
          <li>
            <a href="https://foresignal.biz/terms-of-service">Terms</a>
          </li>
          <li>
            <a href="https://foresignal.biz/refund-policy">Refund Policy</a>
          </li>
          <li>
            <a href="https://foresignal.biz/cookie-policy">Cookie Policy</a>
          </li>
          <li>
            <a href={`mailto:${SUPPORT_EMAIL}`}>Support</a>
          </li>
          <li>
            <a href="https://foresignal.biz">foresignal.biz</a>
          </li>
        </ul>
      </div>
    </footer>
  )
}
