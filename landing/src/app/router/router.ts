import {
  createRootRoute,
  createRoute,
  createRouter as createTanstackRouter,
} from '@tanstack/react-router';
import { RootLayout } from '@/pages/layouts/root-layout';
import { NotFoundPage } from '@/pages/not-found';
import { HomePage } from '@/pages/home';
import { PricingPage } from '@/pages/pricing';
import { AboutPage } from '@/pages/about';
import { ContactPage } from '@/pages/contact';
import { PrivacyPolicyPage } from '@/pages/legal/privacy-policy';
import { TermsOfServicePage } from '@/pages/legal/terms-of-service';
import { CookiePolicyPage } from '@/pages/legal/cookie-policy';
import { AcceptableUsePolicyPage } from '@/pages/legal/acceptable-use-policy';
import { AccessibilityStatementPage } from '@/pages/legal/accessibility-statement';
import { SecurityPage } from '@/pages/legal/security';
import { DpaOverviewPage } from '@/pages/legal/dpa';
import { DoNotSellOrSharePage } from '@/pages/legal/do-not-sell-or-share';

const rootRoute = createRootRoute({
  component: RootLayout,
  notFoundComponent: NotFoundPage,
});

const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/',
  component: HomePage,
});

const pricingRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/pricing',
  component: PricingPage,
});

const aboutRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/about',
  component: AboutPage,
});

const contactRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/contact',
  component: ContactPage,
});

const privacyPolicyRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/privacy-policy',
  component: PrivacyPolicyPage,
});

const termsOfServiceRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/terms-of-service',
  component: TermsOfServicePage,
});

const cookiePolicyRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/cookie-policy',
  component: CookiePolicyPage,
});

const acceptableUsePolicyRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/acceptable-use-policy',
  component: AcceptableUsePolicyPage,
});

const accessibilityRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/accessibility-statement',
  component: AccessibilityStatementPage,
});

const securityRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/security',
  component: SecurityPage,
});

const dpaRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/dpa',
  component: DpaOverviewPage,
});

const doNotSellRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/do-not-sell-or-share',
  component: DoNotSellOrSharePage,
});

const routeTree = rootRoute.addChildren([
  indexRoute,
  pricingRoute,
  aboutRoute,
  contactRoute,
  privacyPolicyRoute,
  termsOfServiceRoute,
  cookiePolicyRoute,
  acceptableUsePolicyRoute,
  accessibilityRoute,
  securityRoute,
  dpaRoute,
  doNotSellRoute,
]);

export function createAppRouter() {
  return createTanstackRouter({
    routeTree,
    scrollRestoration: true,
    scrollRestorationBehavior: 'smooth',
    defaultHashScrollIntoView: { behavior: 'smooth', block: 'start' },
  });
}

declare module '@tanstack/react-router' {
  interface Register {
    router: ReturnType<typeof createAppRouter>;
  }
}


