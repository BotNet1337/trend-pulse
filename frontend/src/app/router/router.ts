import {
  createRootRouteWithContext,
  createRoute,
  createRouter as createTanstackRouter,
  redirect,
} from '@tanstack/react-router';
import type { AuthStore } from '../stores/auth.store';
import { ProtectedLayout, RootLayout } from '@/pages/index/layout';
import {
  AccountSettingsPage,
  AlertDetailPage,
  AlertsListPage,
  AnonymousLayout,
  BillingPage,
  ConfirmEmailChangePage,
  ConfirmEmailPage,
  ForgotPasswordPage,
  NotFoundPage,
  OnboardingPage,
  ResetPasswordPage,
  SignInPage,
  SignUpPage,
  WatchlistsListPage,
  WatchlistCreatePage,
  WatchlistDetailPage,
} from '@/pages';
import { AuthGuard } from './auth-guard';
import { paths } from './path';

export type RouterContext = {
  auth: AuthStore;
};

const rootRoute = createRootRouteWithContext<RouterContext>()({
  component: RootLayout,
  notFoundComponent: NotFoundPage,
});

const anonymousLayoutRoute = createRoute({
  getParentRoute: () => rootRoute,
  id: 'anonymous',
  component: AnonymousLayout,
  beforeLoad: ({ context }) => {
    // Fast path: if AuthStore is already populated (bootstrap done), redirect to
    // home. On cold start the store is null, so we let the component render.
    const authState = context.auth.getState();
    const isAuthenticated = !!authState.user;
    if (isAuthenticated) {
      throw redirect({
        to: paths.home,
        replace: true,
      });
    }
  },
});

// Protected routes use AuthGuard component instead of sync beforeLoad.
// AuthGuard calls useCurrentUser (GET /users/me) on mount; if 401 it redirects
// to /auth/sign-in?redirect=<path>. This works with httpOnly-cookie auth where
// the auth state is not available synchronously at router init time.
const protectedLayoutRoute = createRoute({
  getParentRoute: () => rootRoute,
  id: 'protected',
  component: AuthGuard,
});

const protectedContentRoute = createRoute({
  getParentRoute: () => protectedLayoutRoute,
  id: 'protected-content',
  component: ProtectedLayout,
});

// Home: redirect to watchlists (the main dashboard)
const indexRoute = createRoute({
  getParentRoute: () => protectedContentRoute,
  path: paths.home,
  beforeLoad: () => {
    throw redirect({ to: paths.watchlists.list, replace: true });
  },
  component: () => null,
});

const accountSettingsRoute = createRoute({
  getParentRoute: () => protectedContentRoute,
  path: paths.account.settings,
  component: AccountSettingsPage,
});

const billingRoute = createRoute({
  getParentRoute: () => protectedContentRoute,
  path: paths.billing,
  component: BillingPage,
});

// Alerts routes — all behind protectedContentRoute (AuthGuard)
const alertsListRoute = createRoute({
  getParentRoute: () => protectedContentRoute,
  path: paths.alerts.list,
  component: AlertsListPage,
});

const alertDetailRoute = createRoute({
  getParentRoute: () => protectedContentRoute,
  path: '/alerts/$alertId',
  component: AlertDetailPage,
});

// Watchlist routes — all behind protectedContentRoute (AuthGuard)
const watchlistsListRoute = createRoute({
  getParentRoute: () => protectedContentRoute,
  path: paths.watchlists.list,
  component: WatchlistsListPage,
});

const watchlistCreateRoute = createRoute({
  getParentRoute: () => protectedContentRoute,
  path: paths.watchlists.create,
  component: WatchlistCreatePage,
});

const watchlistDetailRoute = createRoute({
  getParentRoute: () => protectedContentRoute,
  path: '/watchlists/$watchlistId',
  component: WatchlistDetailPage,
});

// Onboarding route — accessible to any authenticated user (TASK-039).
// Decision: do NOT block access for users who already have watchlists; the route
// is just not redirected TO (the redirect criterion is 0 watchlists, handled in
// AuthGuard).  Direct navigation is always allowed.
const onboardingRoute = createRoute({
  getParentRoute: () => protectedContentRoute,
  path: paths.onboarding,
  component: OnboardingPage,
});

const signInRoute = createRoute({
  getParentRoute: () => anonymousLayoutRoute,
  path: paths.auth.signIn,
  component: SignInPage,
});

const signUpRoute = createRoute({
  getParentRoute: () => anonymousLayoutRoute,
  path: paths.auth.signUp,
  component: SignUpPage,
});

const confirmEmailRoute = createRoute({
  getParentRoute: () => anonymousLayoutRoute,
  path: paths.auth.confirmEmail,
  component: ConfirmEmailPage,
});

const confirmEmailChangeRoute = createRoute({
  getParentRoute: () => anonymousLayoutRoute,
  path: paths.auth.confirmEmailChange,
  component: ConfirmEmailChangePage,
});

const forgotPasswordRoute = createRoute({
  getParentRoute: () => anonymousLayoutRoute,
  path: paths.auth.forgotPassword,
  component: ForgotPasswordPage,
});

const resetPasswordRoute = createRoute({
  getParentRoute: () => anonymousLayoutRoute,
  path: paths.auth.resetPassword,
  component: ResetPasswordPage,
});

const routeTree = rootRoute.addChildren([
  protectedLayoutRoute.addChildren([
    protectedContentRoute.addChildren([
      indexRoute,
      accountSettingsRoute,
      billingRoute,
      alertsListRoute,
      alertDetailRoute,
      watchlistsListRoute,
      watchlistCreateRoute,
      watchlistDetailRoute,
      onboardingRoute,
    ]),
  ]),
  anonymousLayoutRoute.addChildren([
    signInRoute,
    signUpRoute,
    confirmEmailRoute,
    confirmEmailChangeRoute,
    forgotPasswordRoute,
    resetPasswordRoute,
  ]),
]);

export function createAppRouter(auth: AuthStore) {
  return createTanstackRouter({
    routeTree,
    context: { auth },
  });
}
