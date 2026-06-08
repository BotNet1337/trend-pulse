import { ArrowRight } from 'lucide-react';
import { Button } from '@/shared/components/button';
import { Link } from '@tanstack/react-router';
import { SITE } from '@/shared/site/constants';

export function FinalCtaSection() {
  return (
    <section id="get-started" className="py-24 px-6 lg:px-20 scroll-mt-16">
      <div className="max-w-4xl mx-auto">
        <div className="bg-linear-to-br from-primary/10 via-primary/5 to-background border border-border rounded-2xl p-12 text-center">
          <h2 className="text-3xl md:text-4xl font-bold mb-4">Ready to post everywhere from one place?</h2>
          <p className="text-lg text-muted-foreground mb-8 max-w-2xl mx-auto">
            Join {SITE.brandName} early access and streamline how you plan, schedule, and publish across your social
            platforms.
          </p>
          <div className="flex flex-col sm:flex-row items-center justify-center gap-4">
            <Button size="lg" asChild>
              <Link to="/contact">
                Get started <ArrowRight className="ml-2 h-4 w-4" />
              </Link>
            </Button>
            <Button size="lg" variant="outline" asChild>
              <Link to="/contact">Schedule a demo</Link>
            </Button>
          </div>
          <p className="text-sm text-muted-foreground mt-6">No credit card required • Join early access</p>
        </div>
      </div>
    </section>
  );
}
