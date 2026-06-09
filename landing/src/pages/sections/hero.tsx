import { ArrowRight } from 'lucide-react';
import { Button } from '@/shared/components/button';
import { Badge } from '@/shared/components/badge';
import { Link } from '@tanstack/react-router';
import { SITE } from '@/shared/site/constants';

export function HeroSection() {
  return (
    <section className="pt-32 pb-16 px-6 lg:px-20 snap-start scroll-mt-16">
      <div className="max-w-4xl mx-auto text-center">
        <Badge variant="secondary" className="mb-6">
          Early Access • Cross-platform publishing
        </Badge>

        <h1 className="text-4xl md:text-5xl lg:text-6xl font-bold mb-6 tracking-tight">
          Welcome to {SITE.brandName}
        </h1>

        <p className="text-lg md:text-xl text-muted-foreground mb-8 max-w-2xl mx-auto">
          Plan, schedule, and publish posts across all your social platforms from one workspace—one workflow instead of
          juggling every network separately.
        </p>

        <div className="flex flex-col sm:flex-row items-center justify-center gap-4 mb-8">
          <Button size="lg" className="w-full sm:w-auto" asChild>
            <Link to="/" hash="get-started">
              Get started <ArrowRight className="ml-2 h-4 w-4" />
            </Link>
          </Button>
          <Button size="lg" variant="outline" className="w-full sm:w-auto" asChild>
            <Link to="/contact">Contact sales</Link>
          </Button>
        </div>

        <p className="text-sm text-muted-foreground">No credit card required • Join early access</p>
      </div>

      <div className="max-w-5xl mx-auto mt-16">
        <div className="bg-muted/50 rounded-xl border border-border aspect-video flex items-center justify-center">
          <p className="text-muted-foreground">Product Screenshot Placeholder</p>
        </div>
      </div>
    </section>
  );
}


