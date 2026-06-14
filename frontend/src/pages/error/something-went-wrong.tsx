import React from 'react'
import { Link } from '@tanstack/react-router'
import { paths } from "@/app/router/path"
import { Button } from "@/shared/components/button"

export const SomethingWentWrongPage: React.FC = () => {
  return (
    <div className="fs-app">
      <div className="app-aurora" aria-hidden="true">
        <div className="blob blob-1" />
        <div className="blob blob-2" />
        <div className="blob blob-3" />
      </div>

      <main className="fs-main error-main">
        <div className="fs-container">
          <div className="error-wrap">
            <div>
              <h1 className="error-code">Oops!</h1>
              <p className="error-title">Something went wrong</p>
              <p className="error-text">
                We encountered an unexpected error. Please try again later or contact support if the problem persists.
              </p>
            </div>

            <div className="error-actions">
              <Button asChild variant="outline">
                <Link to={paths.home}>Go Home</Link>
              </Button>
              <Button asChild>
                <Link to={paths.auth.signIn}>Sign In</Link>
              </Button>
            </div>
          </div>
        </div>
      </main>
    </div>
  )
}


