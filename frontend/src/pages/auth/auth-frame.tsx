import * as React from 'react'

import { BRAND_NAME } from '@/shared/config'
import { AuroraMark } from '@/shared/components/aurora-mark'
import { ComplianceFooter } from '@/shared/components/compliance-footer'

export interface AuthFrameProps {
  children: React.ReactNode
}

/**
 * AuthFrame — shared chrome for every auth screen (sign-in, sign-up, forgot /
 * reset password, confirm email). Ported from the Aurora app design: a subdued
 * aurora backdrop, centred brand wordmark, the card slot, and the compliance
 * footer. No app bar — the user is not signed in.
 */
export const AuthFrame: React.FC<AuthFrameProps> = ({ children }) => {
  return (
    <div className="fs-app">
      <div className="app-aurora" aria-hidden="true">
        <div className="blob blob-1" />
        <div className="blob blob-2" />
        <div className="blob blob-3" />
      </div>

      <main id="main" className="fs-main fs-auth-main">
        <div className="fs-container">
          <div className="fs-auth-wrap">
            <div className="fs-auth-brand">
              <AuroraMark size={32} />
              <span className="fs-auth-brand__name">{BRAND_NAME}</span>
            </div>

            {children}
          </div>
        </div>
      </main>

      <ComplianceFooter />
    </div>
  )
}
