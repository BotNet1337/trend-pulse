export const paths = {
  home: '/',
  onboarding: '/onboarding',
  account: {
    settings: '/account/settings',
  },
  auth: {
    signIn: '/auth/sign-in',
    signUp: '/auth/sign-up',
    confirmEmail: '/auth/email/confirm',
    confirmEmailChange: '/auth/email/confirm-change',
    forgotPassword: '/auth/password/forgot',
    resetPassword: '/auth/password/reset',
  },
  watchlists: {
    list: '/watchlists',
    create: '/watchlists/new',
    detail: (id: number | string) => `/watchlists/${id}`,
  },
  alerts: {
    list: '/alerts',
    detail: (id: number | string) => `/alerts/${id}`,
  },
  billing: '/billing',
} as const;
