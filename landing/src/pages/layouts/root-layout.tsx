import * as React from 'react';
import { Link, Outlet } from '@tanstack/react-router';
import { Button } from '@/shared/components/button';
import { SITE } from '@/shared/site/constants';
import { ThemeToggle } from '@/shared/components/theme-toggle';
import { Menu, X } from 'lucide-react';
import { useLocation } from '@tanstack/react-router';
import { track, EVENT_SIGN_UP_CLICK } from '@/shared/analytics/track';

export function RootLayout() {
  const [mobileMenuOpen, setMobileMenuOpen] = React.useState(false);
  const pathname = useLocation({ select: (l) => l.pathname });
  // TASK-067: rendered only when the showcase channel exists (owner fills after TASK-070).
  const showcaseTelegramUrl = (SITE as { showcaseTelegramUrl?: string }).showcaseTelegramUrl ?? '';

  React.useEffect(() => {
    const enabled = pathname === '/';
    const root = document.documentElement;

    root.classList.toggle('home-scroll-snap', enabled);

    if (import.meta.env.DEV) {
      try {
         
        console.debug('[landing] home scroll-snap', { enabled, pathname });
      } catch {
        // ignore
      }
    }

    return () => {
      root.classList.remove('home-scroll-snap');
    };
  }, [pathname]);

  React.useEffect(() => {
    if (!import.meta.env.DEV) return;
    try {
      const hash = window.location.hash;
      if (!hash) return;
      const id = hash.startsWith('#') ? hash.slice(1) : hash;
      const el = document.getElementById(id);

       
      console.debug('[landing] hash target', { hash, found: Boolean(el) });
    } catch {
      // ignore
    }
  }, [pathname]);

  return (
    <div className="min-h-dvh">
      <nav className="fixed top-0 left-0 right-0 z-50 bg-background/80 backdrop-blur-md border-b border-border">
        <div className="max-w-7xl mx-auto px-6 lg:px-20">
          <div className="flex items-center justify-between h-16">
            <Link to="/" className="flex items-center gap-2 hover:opacity-80 transition-opacity" aria-label={`${SITE.brandName} home`}>
              <div className="w-8 h-8 bg-aurora-button rounded-lg flex items-center justify-center shadow-brand">
                <span className="text-primary-foreground font-bold text-xs">TP</span>
              </div>
              <span className="font-semibold text-lg">{SITE.brandName}</span>
            </Link>

            <div className="hidden md:flex items-center gap-8">
              <Link to="/pricing" className="text-muted-foreground hover:text-foreground transition-colors">
                Pricing
              </Link>
              <Link to="/about" className="text-muted-foreground hover:text-foreground transition-colors">
                About
              </Link>
              <Link to="/" hash="faq" className="text-muted-foreground hover:text-foreground transition-colors">
                FAQ
              </Link>
              <Link to="/contact" className="text-muted-foreground hover:text-foreground transition-colors">
                Contact
              </Link>
            </div>

            <div className="hidden md:flex items-center gap-3">
              <ThemeToggle />
              <Button variant="ghost" asChild>
                <Link to="/contact">Contact</Link>
              </Button>
              <Button asChild>
                <a
                  href={(SITE as { signupUrl?: string }).signupUrl ?? '/sign-up'}
                  onClick={() => track(EVENT_SIGN_UP_CLICK)}
                >
                  {SITE.ctaText}
                </a>
              </Button>
            </div>

            <div className="md:hidden flex items-center gap-2">
              <ThemeToggle />
              <button
                className="p-2"
                onClick={() => setMobileMenuOpen((v) => !v)}
                aria-label="Toggle menu"
                type="button"
              >
                {mobileMenuOpen ? <X className="h-6 w-6" /> : <Menu className="h-6 w-6" />}
              </button>
            </div>
          </div>

          {mobileMenuOpen ? (
            <div className="md:hidden py-4 border-t border-border">
              <div className="flex flex-col gap-4">
                <Link
                  to="/pricing"
                  className="text-muted-foreground hover:text-foreground transition-colors"
                  onClick={() => setMobileMenuOpen(false)}
                >
                  Pricing
                </Link>
                <Link
                  to="/about"
                  className="text-muted-foreground hover:text-foreground transition-colors"
                  onClick={() => setMobileMenuOpen(false)}
                >
                  About
                </Link>
                <Link
                  to="/"
                  hash="faq"
                  className="text-muted-foreground hover:text-foreground transition-colors"
                  onClick={() => setMobileMenuOpen(false)}
                >
                  FAQ
                </Link>
                <Link
                  to="/contact"
                  className="text-muted-foreground hover:text-foreground transition-colors"
                  onClick={() => setMobileMenuOpen(false)}
                >
                  Contact
                </Link>
                <div className="flex flex-col gap-2 pt-4 border-t border-border">
                  <Button variant="ghost" asChild>
                    <Link to="/contact" onClick={() => setMobileMenuOpen(false)}>
                      Contact
                    </Link>
                  </Button>
                  <Button asChild>
                    <a
                      href={(SITE as { signupUrl?: string }).signupUrl ?? '/sign-up'}
                      onClick={() => {
                        track(EVENT_SIGN_UP_CLICK);
                        setMobileMenuOpen(false);
                      }}
                    >
                      {SITE.ctaText}
                    </a>
                  </Button>
                </div>
              </div>
            </div>
          ) : null}
        </div>
      </nav>

      <main className="pt-16">
        <Outlet />
      </main>

      <footer className="bg-muted/30 border-t border-border">
        <div className="max-w-7xl mx-auto px-6 lg:px-20 py-12">
          <div className="grid grid-cols-1 md:grid-cols-4 gap-8 mb-8">
            <div>
              <Link to="/" className="flex items-center gap-2 mb-4 hover:opacity-80 transition-opacity w-fit" aria-label={`${SITE.brandName} home`}>
                <div className="w-8 h-8 bg-aurora-button rounded-lg flex items-center justify-center shadow-brand">
                  <span className="text-primary-foreground font-bold text-xs">TP</span>
                </div>
                <span className="font-semibold text-lg">{SITE.brandName}</span>
              </Link>
              <p className="text-sm text-muted-foreground">{SITE.valueProp}</p>
              <p className="text-sm text-muted-foreground mt-3 font-medium">Compliance</p>
              <p className="text-sm text-muted-foreground">Public channels only · 48-hour retention</p>
              <p className="text-sm text-muted-foreground mt-2">{SITE.legal.entityName}</p>
              <p className="text-sm text-muted-foreground">{SITE.legal.address}</p>
            </div>

            <div>
              <h4 className="mb-4">Product</h4>
              <ul className="space-y-2">
                <li><Link to="/pricing" className="text-sm text-muted-foreground hover:text-foreground transition-colors">Pricing</Link></li>
                <li><Link to="/" hash="faq" className="text-sm text-muted-foreground hover:text-foreground transition-colors">FAQ</Link></li>
                <li><Link to="/blog" className="text-sm text-muted-foreground hover:text-foreground transition-colors">Blog</Link></li>
                <li><a href="#docs" className="text-sm text-muted-foreground hover:text-foreground transition-colors">Documentation</a></li>
                {showcaseTelegramUrl ? (
                  <li>
                    <a
                      href={showcaseTelegramUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-sm text-muted-foreground hover:text-foreground transition-colors"
                    >
                      Telegram showcase
                    </a>
                  </li>
                ) : null}
              </ul>
            </div>

            <div>
              <h4 className="mb-4">Company</h4>
              <ul className="space-y-2">
                <li><Link to="/about" className="text-sm text-muted-foreground hover:text-foreground transition-colors">About</Link></li>
                <li><Link to="/contact" className="text-sm text-muted-foreground hover:text-foreground transition-colors">Contact</Link></li>
                <li><Link to="/security" className="text-sm text-muted-foreground hover:text-foreground transition-colors">Security</Link></li>
              </ul>
            </div>

            <div>
              <h4 className="mb-4">Legal</h4>
              <ul className="space-y-2">
                <li><Link to="/privacy-policy" className="text-sm text-muted-foreground hover:text-foreground transition-colors">Privacy Policy</Link></li>
                <li><Link to="/terms-of-service" className="text-sm text-muted-foreground hover:text-foreground transition-colors">Terms of Service</Link></li>
                <li><Link to="/refund-policy" className="text-sm text-muted-foreground hover:text-foreground transition-colors">Refund Policy</Link></li>
                <li><Link to="/cookie-policy" className="text-sm text-muted-foreground hover:text-foreground transition-colors">Cookie Policy</Link></li>
                <li><Link to="/acceptable-use-policy" className="text-sm text-muted-foreground hover:text-foreground transition-colors">Acceptable Use</Link></li>
                <li><Link to="/do-not-sell-or-share" className="text-sm text-muted-foreground hover:text-foreground transition-colors">Do Not Sell/Share</Link></li>
                <li><Link to="/accessibility-statement" className="text-sm text-muted-foreground hover:text-foreground transition-colors">Accessibility</Link></li>
                <li><Link to="/dpa" className="text-sm text-muted-foreground hover:text-foreground transition-colors">DPA Overview</Link></li>
              </ul>
            </div>
          </div>

          <div className="pt-8 border-t border-border flex flex-col md:flex-row justify-between items-center gap-4">
            <p className="text-sm text-muted-foreground">© {new Date().getFullYear()} {SITE.brandName}. All rights reserved.</p>
            <div className="flex items-center gap-6">
              <button
                className="text-sm text-muted-foreground hover:text-foreground transition-colors"
                type="button"
                onClick={() => window.dispatchEvent(new CustomEvent('open-cookie-preferences'))}
              >
                Cookie Preferences
              </button>
            </div>
          </div>
        </div>
      </footer>
    </div>
  );
}



