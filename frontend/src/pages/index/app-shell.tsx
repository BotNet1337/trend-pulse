import * as React from 'react'
import { Link } from '@tanstack/react-router'

import { paths } from '@/app/router/path'
import { BRAND_NAME, SUPPORT_EMAIL } from '@/shared/config'
import { AuroraMark } from '@/shared/components/aurora-mark'
import { ComplianceFooter } from '@/shared/components/compliance-footer'
import { useCurrentUser } from '@/entities/viewer/model'
import { useLogout } from '@/features/auth'

/** Two-letter avatar initials derived from an email's local part. */
function initialsFromEmail(email: string): string {
  const local = email.split('@')[0] ?? ''
  const parts = local.split(/[._-]+/).filter(Boolean)
  if (parts.length >= 2) {
    return (parts[0][0] + parts[1][0]).toUpperCase()
  }
  return local.slice(0, 2).toUpperCase() || '?'
}

/** Truncated email shown on the avatar chip (e.g. "yaroslav@…"). */
function shortEmail(email: string): string {
  const local = email.split('@')[0] ?? email
  return `${local}@…`
}

interface AccountMenuProps {
  email: string
  /** Superuser → expose the admin links (TG pool). Server enforces 403. */
  isSuperuser: boolean
}

/**
 * Account dropdown — the avatar chip + glass menu from the Aurora app design.
 * Menu items: email header, Settings, Invite friends, Support, Sign out.
 * Accessible: toggled by click, closed on outside-click and Escape; Sign out
 * calls the existing logout mutation (behaviour unchanged).
 */
const AccountMenu: React.FC<AccountMenuProps> = ({ email, isSuperuser }) => {
  const [open, setOpen] = React.useState(false)
  const containerRef = React.useRef<HTMLDivElement>(null)
  const logoutMutation = useLogout()
  const menuId = React.useId()
  const triggerId = React.useId()

  React.useEffect(() => {
    if (!open) return
    const onPointerDown = (event: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setOpen(false)
      }
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('mousedown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [open])

  return (
    <div className="fs-appbar__account" ref={containerRef}>
      <button
        type="button"
        id={triggerId}
        className="fs-appbar__user"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={menuId}
        onClick={() => setOpen((v) => !v)}
      >
        <span className="fs-appbar__avatar" aria-hidden="true">
          {initialsFromEmail(email)}
        </span>
        <span className="fs-appbar__name">{shortEmail(email)}</span>
        <svg
          width="12"
          height="12"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.4"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="m6 9 6 6 6-6" />
        </svg>
      </button>

      <div className="fs-menu" id={menuId} role="menu" aria-labelledby={triggerId} hidden={!open}>
        <div className="fs-menu__header" role="presentation" title={email}>
          {email}
        </div>
        <Link
          className="fs-menu__item"
          to={paths.account.settings}
          role="menuitem"
          onClick={() => setOpen(false)}
        >
          Settings
        </Link>
        <Link
          className="fs-menu__item"
          to={paths.account.invite}
          role="menuitem"
          onClick={() => setOpen(false)}
        >
          Invite friends
        </Link>
        <a className="fs-menu__item" href={`mailto:${SUPPORT_EMAIL}`} role="menuitem">
          Support
        </a>
        {isSuperuser && (
          <>
            <hr className="fs-menu__separator" role="separator" />
            <Link
              className="fs-menu__item"
              to={paths.admin.pool}
              role="menuitem"
              onClick={() => setOpen(false)}
            >
              TG pool (admin)
            </Link>
          </>
        )}
        <hr className="fs-menu__separator" role="separator" />
        <button
          type="button"
          className="fs-menu__item fs-menu__item--danger"
          role="menuitem"
          disabled={logoutMutation.isPending}
          onClick={() => {
            setOpen(false)
            logoutMutation.mutate()
          }}
        >
          {logoutMutation.isPending ? 'Signing out…' : 'Sign out'}
        </button>
      </div>
    </div>
  )
}

export interface AppShellProps {
  children: React.ReactNode
}

/**
 * AppShell — authenticated chrome ported from designs/trendPulse/variants/app:
 * a sticky glass `.fs-appbar` (brand + nav + account dropdown) and the
 * `.fs-appfooter` compliance footer, with the page content rendered in between.
 */
export const AppShell: React.FC<AppShellProps> = ({ children }) => {
  const { data: user } = useCurrentUser()
  const email = user?.email ?? ''
  const isSuperuser = user?.is_superuser === true

  return (
    <div className="fs-app">
      <div className="app-aurora" aria-hidden="true">
        <div className="blob blob-1" />
        <div className="blob blob-2" />
        <div className="blob blob-3" />
      </div>

      <header className="fs-appbar">
        <nav className="fs-container" aria-label="App navigation">
          <div className="fs-appbar__inner">
            <Link className="fs-appbar__brand" to={paths.watchlists.list} aria-label={`${BRAND_NAME} home`}>
              <AuroraMark size={26} />
              <span>{BRAND_NAME}</span>
            </Link>

            <ul className="fs-appbar__nav">
              <li>
                <Link
                  className="fs-appbar__link"
                  to={paths.watchlists.list}
                  activeProps={{ 'aria-current': 'page' }}
                >
                  Watchlists
                </Link>
              </li>
              <li>
                <Link
                  className="fs-appbar__link"
                  to={paths.alerts.list}
                  activeProps={{ 'aria-current': 'page' }}
                >
                  Alerts
                </Link>
              </li>
              <li>
                <Link
                  className="fs-appbar__link"
                  to={paths.billing}
                  activeProps={{ 'aria-current': 'page' }}
                >
                  Billing
                </Link>
              </li>
            </ul>

            <span className="fs-appbar__spacer" />

            {email && <AccountMenu email={email} isSuperuser={isSuperuser} />}
          </div>
        </nav>
      </header>

      {children}

      <ComplianceFooter />
    </div>
  )
}
