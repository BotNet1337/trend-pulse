import { Outlet } from '@tanstack/react-router'
import React from 'react'

import { AppShell } from './app-shell'

export const RootLayout: React.FC = () => {
  return (
    <main className="min-h-dvh">
      <Outlet />
    </main>
  )
}

/**
 * Authenticated shell. Renders the shared Aurora app chrome (sticky `.fs-appbar`
 * with brand + nav + account dropdown, and the `.fs-appfooter` compliance
 * footer) around the active protected page. Pages render only their own
 * `<main className="fs-main">` content between the bar and footer.
 */
export const ProtectedLayout: React.FC = () => {
  return (
    <AppShell>
      <Outlet />
    </AppShell>
  )
}
