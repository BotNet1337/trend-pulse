import type { InitialState } from '../shared/ssr/initial-state.types';

declare global {
  interface Window {
    /**
     * Server-injected hydration payload (TASK-036). All fields are optional
     * because hydration is best-effort — anything missing is filled by the
     * client at runtime.
     */
    __INITIAL_STATE__?: Partial<InitialState>;
    $_TSR?: unknown;
  }
}

export {};
