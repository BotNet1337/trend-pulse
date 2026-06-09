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
  AnonymousLayout,
  ConfirmEmailChangePage,
  ConfirmEmailPage,
  ForgotPasswordPage,
  NotFoundPage,
  ResetPasswordPage,
  SignInPage,
  SignUpPage,
} from '@/pages';
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

const protectedLayoutRoute = createRoute({
  getParentRoute: () => rootRoute,
  id: 'protected',
  beforeLoad: ({ context, location }) => {
    const authState = context.auth.getState();
    const isAuthenticated = !!authState.user;
    if (!isAuthenticated) {
      throw redirect({
        to: paths.auth.signIn,
        search: {
          redirect: location.href,
        },
      });
    }
  },
  component: ProtectedLayout,
});

// Home: redirect to account settings (placeholder for C2 watchlists dashboard)
const indexRoute = createRoute({
  getParentRoute: () => protectedLayoutRoute,
  path: paths.home,
  beforeLoad: () => {
    throw redirect({ to: paths.account.settings, replace: true });
  },
  component: () => null,
});

const accountSettingsRoute = createRoute({
  getParentRoute: () => protectedLayoutRoute,
  path: paths.account.settings,
  component: AccountSettingsPage,
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
    indexRoute,
    accountSettingsRoute,
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
