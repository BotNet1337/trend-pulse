import { Outlet } from '@tanstack/react-router'
import React from 'react'

export const RootLayout: React.FC = () => {
  return (
    <main className="min-h-dvh">
      <Outlet />
    </main>
  )
}

/**
 * Authenticated shell. Each protected page now owns its own chrome (top bar /
 * workspace switcher), so this layout is intentionally a thin pass-through.
 */
export const ProtectedLayout: React.FC = () => {
  return <Outlet />
}
