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
  ChannelConnectFailedPage,
  ChannelConnectedPage,
  ConfirmEmailChangePage,
  ConfirmEmailPage,
  ForgotPasswordPage,
  ModerationDetailPage,
  ModerationQueuePage,
  NotFoundPage,
  ResetPasswordPage,
  SignInPage,
  SignUpPage,
  WorkspaceCalendarPage,
  WorkspaceChannelsPage,
  WorkspaceDashboardPage,
  WorkspaceDetailPage,
  WorkspacePostDetailsPage,
  WorkspacePostsPage,
  WorkspacePublicationDetailsPage,
  WorkspaceSettingsPage,
  WorkspacesSelectPage,
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
        to: paths.workspaces.list,
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

const indexRoute = createRoute({
  getParentRoute: () => protectedLayoutRoute,
  path: paths.home,
  beforeLoad: () => {
    throw redirect({ to: paths.workspaces.list, replace: true });
  },
  component: () => null,
});

const workspacesRoute = createRoute({
  getParentRoute: () => protectedLayoutRoute,
  path: paths.workspaces.list,
  component: WorkspacesSelectPage,
});

const workspaceDetailRoute = createRoute({
  getParentRoute: () => protectedLayoutRoute,
  path: '/workspaces/$id',
  component: WorkspaceDetailPage,
});

const workspaceDashboardRoute = createRoute({
  getParentRoute: () => protectedLayoutRoute,
  path: '/workspaces/$id/dashboard',
  component: WorkspaceDashboardPage,
});

const workspaceChannelsRoute = createRoute({
  getParentRoute: () => protectedLayoutRoute,
  path: '/workspaces/$id/channels',
  component: WorkspaceChannelsPage,
});

const workspacePostsRoute = createRoute({
  getParentRoute: () => protectedLayoutRoute,
  path: '/workspaces/$id/posts',
  component: WorkspacePostsPage,
});

const workspaceCalendarRoute = createRoute({
  getParentRoute: () => protectedLayoutRoute,
  path: '/workspaces/$id/calendar',
  component: WorkspaceCalendarPage,
});

const workspaceSettingsRoute = createRoute({
  getParentRoute: () => protectedLayoutRoute,
  path: '/workspaces/$id/settings',
  component: WorkspaceSettingsPage,
});

const accountSettingsRoute = createRoute({
  getParentRoute: () => protectedLayoutRoute,
  path: '/account/settings',
  component: AccountSettingsPage,
})

// Admin moderation surface (TASK-072). Global, cross-workspace — not nested
// under a workspace. Access is permission-gated client-side (UX) by the page
// itself (`useCanModerate`); the real boundary is the API 403
// (`@RequirePermission('ModerateContent')`), handled in the queue/detail views.
const moderationQueueRoute = createRoute({
  getParentRoute: () => protectedLayoutRoute,
  path: paths.moderation.queue,
  component: ModerationQueuePage,
})

const moderationDetailRoute = createRoute({
  getParentRoute: () => protectedLayoutRoute,
  path: '/moderation/$requestId',
  component: ModerationDetailPage,
});

const workspacePostDetailsRoute = createRoute({
  getParentRoute: () => protectedLayoutRoute,
  path: '/workspaces/$id/posts/$postId',
  component: WorkspacePostDetailsPage,
});

const workspacePublicationDetailsRoute = createRoute({
  getParentRoute: () => protectedLayoutRoute,
  path: '/workspaces/$id/posts/$postId/publications/$publicationId',
  component: WorkspacePublicationDetailsPage,
});

// Popup callback routes are intentionally public — they only postMessage the
// result to the opener and close themselves. Putting them under
// `protectedLayoutRoute` would re-prompt the user for sign-in inside the popup
// when the auth store hasn't hydrated yet, defeating the whole flow.
const channelConnectedRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/workspaces/$id/channels/$channelId/connected',
  component: ChannelConnectedPage,
});

const channelConnectFailedRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: paths.workspaces.channelConnectFailed,
  component: ChannelConnectFailedPage,
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
  channelConnectedRoute,
  channelConnectFailedRoute,
  protectedLayoutRoute.addChildren([
    indexRoute,
    workspacesRoute,
    workspaceDetailRoute,
    workspaceDashboardRoute,
    workspaceChannelsRoute,
    workspacePostsRoute,
    workspaceCalendarRoute,
    workspaceSettingsRoute,
    accountSettingsRoute,
    workspacePostDetailsRoute,
    workspacePublicationDetailsRoute,
    moderationQueueRoute,
    moderationDetailRoute,
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
