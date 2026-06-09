import * as React from 'react';
import { X } from 'lucide-react';
import { Button } from '@/shared/components/button';
import { Switch } from '@/shared/components/switch';

type CookieConsent = 'all' | 'essential' | 'custom';
type CookiePreferences = { essential: true; analytics: boolean; marketing: boolean };

const CONSENT_KEY = 'cookie-consent';
const PREFS_KEY = 'cookie-preferences';

function safeGet<T>(key: string): T | null {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return null;
    return JSON.parse(raw) as T;
  } catch {
    return null;
  }
}

function safeSet(key: string, value: string) {
  try {
    localStorage.setItem(key, value);
  } catch {
    // ignore
  }
}

export function CookieBanner() {
  const [mounted, setMounted] = React.useState(false);
  const [isVisible, setIsVisible] = React.useState(false);
  const [showPreferences, setShowPreferences] = React.useState(false);

  const [preferences, setPreferences] = React.useState<CookiePreferences>({
    essential: true,
    analytics: false,
    marketing: false,
  });

  React.useEffect(() => {
    setMounted(true);
    const consent = (localStorage.getItem(CONSENT_KEY) as CookieConsent | null) ?? null;
    setIsVisible(!consent);

    const storedPrefs = safeGet<CookiePreferences>(PREFS_KEY);
    if (storedPrefs) setPreferences({ ...storedPrefs, essential: true });

    const onOpen = () => setShowPreferences(true);
    window.addEventListener('open-cookie-preferences', onOpen as EventListener);
    return () => window.removeEventListener('open-cookie-preferences', onOpen as EventListener);
  }, []);

  if (!mounted) return null;

  const acceptAll = () => {
    safeSet(CONSENT_KEY, 'all');
    setIsVisible(false);
  };

  const rejectAll = () => {
    safeSet(CONSENT_KEY, 'essential');
    setIsVisible(false);
  };

  const savePreferences = () => {
    safeSet(PREFS_KEY, JSON.stringify(preferences));
    safeSet(CONSENT_KEY, 'custom');
    setShowPreferences(false);
    setIsVisible(false);
  };

  return (
    <>
      {isVisible ? (
        <div className="fixed bottom-0 left-0 right-0 z-50 bg-card border-t border-border shadow-lg">
          <div className="max-w-7xl mx-auto px-6 lg:px-20 py-6">
            <div className="flex flex-col md:flex-row items-start md:items-center justify-between gap-4 relative">
              <div className="flex-1">
                <h3 className="mb-2">Cookie Consent</h3>
                <p className="text-sm text-muted-foreground">
                  We use cookies to enhance your experience, analyze site traffic, and personalize content. You can manage
                  your preferences or accept all cookies.
                </p>
              </div>

              <div className="flex flex-wrap items-center gap-3">
                <Button variant="ghost" size="sm" onClick={() => setShowPreferences(true)}>
                  Customize
                </Button>
                <Button variant="ghost" size="sm" onClick={rejectAll}>
                  Reject All
                </Button>
                <Button size="sm" onClick={acceptAll}>
                  Accept All
                </Button>
              </div>

              <button
                onClick={rejectAll}
                className="absolute top-0 right-0 md:relative md:top-0 md:right-0 p-1"
                aria-label="Close"
                type="button"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {showPreferences ? (
        <div className="fixed inset-0 z-[60] flex items-center justify-center">
          <div className="absolute inset-0 bg-black/50" onClick={() => setShowPreferences(false)} />
          <div className="relative bg-card rounded-lg shadow-xl max-w-2xl w-full mx-4 max-h-[90vh] overflow-y-auto">
            <div className="p-6">
              <div className="flex items-start justify-between mb-6">
                <div>
                  <h2 className="mb-2">Cookie Preferences</h2>
                  <p className="text-sm text-muted-foreground">
                    Manage your cookie preferences below. Essential cookies are required for the site to function.
                  </p>
                </div>
                <button onClick={() => setShowPreferences(false)} className="p-1" aria-label="Close" type="button">
                  <X className="h-5 w-5" />
                </button>
              </div>

              <div className="space-y-6">
                <div className="flex items-start justify-between gap-4 pb-4 border-b border-border">
                  <div className="flex-1">
                    <h4 className="mb-1">Essential Cookies</h4>
                    <p className="text-sm text-muted-foreground">
                      Required for the website to function properly. Cannot be disabled.
                    </p>
                  </div>
                  <Switch checked disabled />
                </div>

                <div className="flex items-start justify-between gap-4 pb-4 border-b border-border">
                  <div className="flex-1">
                    <h4 className="mb-1">Analytics Cookies</h4>
                    <p className="text-sm text-muted-foreground">
                      Help us understand how visitors interact with our website by collecting anonymous information.
                    </p>
                  </div>
                  <Switch
                    checked={preferences.analytics}
                    onCheckedChange={(checked) => setPreferences((p) => ({ ...p, analytics: checked }))}
                  />
                </div>

                <div className="flex items-start justify-between gap-4">
                  <div className="flex-1">
                    <h4 className="mb-1">Marketing Cookies</h4>
                    <p className="text-sm text-muted-foreground">
                      Used to track visitors across websites to display relevant advertisements.
                    </p>
                  </div>
                  <Switch
                    checked={preferences.marketing}
                    onCheckedChange={(checked) => setPreferences((p) => ({ ...p, marketing: checked }))}
                  />
                </div>
              </div>

              <div className="flex justify-end gap-3 mt-6 pt-6 border-t border-border">
                <Button variant="ghost" onClick={() => setShowPreferences(false)}>
                  Cancel
                </Button>
                <Button onClick={savePreferences}>Save Preferences</Button>
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}


