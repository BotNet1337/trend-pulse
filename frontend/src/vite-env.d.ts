/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_BRAND_NAME?: string
  readonly VITE_HELP_URL?: string
  readonly VITE_SUPPORT_EMAIL?: string
  /** Google reCAPTCHA v2 public site key. Set in prod → captcha on; unset → off. */
  readonly VITE_RECAPTCHA_SITE_KEY?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
