import { Outlet } from '@tanstack/react-router'
import React from 'react'


export const PublicLayout: React.FC = () => {
  return (
    <main>
      <Outlet />
    </main>
  )
}

export const AnonymousLayout: React.FC = () => {
  return (
    <main>
      <Outlet />
    </main>
  )
}