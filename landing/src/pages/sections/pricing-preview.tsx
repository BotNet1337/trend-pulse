import { Button } from '@/shared/components/button';
import { Badge } from '@/shared/components/badge';
import { Link } from '@tanstack/react-router';

export function PricingPreviewSection() {
  return (
    <section id="pricing" className="py-24 px-6 lg:px-20 bg-muted/20 snap-start scroll-mt-16">
      <div className="max-w-6xl mx-auto">
        <div className="text-center mb-16">
          <h2 className="text-3xl md:text-4xl font-bold mb-4">Early Access Pricing</h2>
          <p className="text-lg text-muted-foreground max-w-2xl mx-auto mb-4">
            Early access plans are still taking shape. Terms can change as we add publishing features and platform
            integrations.
          </p>
          <Badge variant="outline">In development</Badge>
        </div>

        <div className="bg-card border border-border rounded-lg p-8 max-w-2xl mx-auto text-center">
          <h3 className="mb-2">Want pricing updates?</h3>
          <p className="text-sm text-muted-foreground mb-6">
            Join the waitlist and we’ll email you when pricing terms and access updates are published.
          </p>
          <div className="flex flex-col sm:flex-row gap-3 justify-center">
            <Button asChild>
              <Link to="/contact">Join the waitlist</Link>
            </Button>
            <Button variant="outline" asChild>
              <Link to="/pricing">See pricing page</Link>
            </Button>
          </div>
        </div>
      </div>
    </section>
  );
}


