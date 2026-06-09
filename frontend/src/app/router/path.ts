export const paths = {
  home: '/',
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
} as const;
