// Minimal Vite-like `import.meta.env` typing.
// Note: this repo uses `rolldown-vite`, which may not ship `vite/client` types.
declare global {
  interface ImportMetaEnv {
    readonly MODE: string;
    readonly DEV: boolean;
    readonly PROD: boolean;
    readonly SSR: boolean;
    readonly VITE_BRAND_NAME?: string;
    readonly VITE_SITE_URL?: string;
    readonly [key: string]: string | boolean | undefined;
  }

  interface ImportMeta {
    readonly env: ImportMetaEnv;
  }
}

export { };


