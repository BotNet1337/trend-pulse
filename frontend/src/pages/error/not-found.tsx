import React from 'react'
import { Link } from '@tanstack/react-router'
import { paths } from "@/app/router/path"
import { Button } from "@/shared/components/button"

export const NotFoundPage: React.FC = () => {
  return (
    <div className="min-h-screen flex items-center justify-center p-4">
      <div className="text-center space-y-6 max-w-md">
        <div className="space-y-2">
          <h1 className="text-4xl font-bold tracking-tight">404</h1>
          <h2 className="text-2xl font-semibold text-muted-foreground">Page not found</h2>
          <p className="text-muted-foreground">
            The page you're looking for doesn't exist or has been moved. Please check the URL or return to the homepage.
          </p>
        </div>
        
        <div className="flex justify-center gap-4">
          <Button asChild variant="outline">
            <Link to={paths.home}>Go Home</Link>
          </Button>
          <Button asChild>
            <Link to={paths.auth.signIn}>Sign In</Link>
          </Button>
        </div>
      </div>
    </div>
  )
}
