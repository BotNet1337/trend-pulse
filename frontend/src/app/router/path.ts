export const paths = {
  home: '/',
  workspaces: {
    list: '/workspaces',
    detail: (id: string) => `/workspaces/${id}` as const,
    dashboard: (id: string) => `/workspaces/${id}/dashboard` as const,
    channels: (id: string) => `/workspaces/${id}/channels` as const,
    channelConnected: (id: string, channelId: string) =>
      `/workspaces/${id}/channels/${channelId}/connected` as const,
    channelConnectFailed: '/channels/connect-failed',
    posts: (id: string) => `/workspaces/${id}/posts` as const,
    calendar: (id: string) => `/workspaces/${id}/calendar` as const,
    settings: (id: string) => `/workspaces/${id}/settings` as const,
    postDetails: (id: string, postId: string) =>
      `/workspaces/${id}/posts/${postId}` as const,
    publicationDetails: (id: string, postId: string, publicationId: string) =>
      `/workspaces/${id}/posts/${postId}/publications/${publicationId}` as const,
  },
  account: {
    settings: '/account/settings',
  },
  moderation: {
    queue: '/moderation',
    detail: (requestId: string) => `/moderation/${requestId}` as const,
  },
  auth: {
    signIn: '/auth/sign-in',
    signUp: '/auth/sign-up',
    confirmEmail: '/auth/email/confirm',
    confirmEmailChange: '/auth/email/confirm-change',
    forgotPassword: '/auth/password/forgot',
    resetPassword: '/auth/password/reset',
  },
} as const;
