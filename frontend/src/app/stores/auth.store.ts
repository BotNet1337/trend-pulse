import type { JwtUser } from "@/entities/user/model";
import { createStore, type StoreApi } from "zustand";
import { useStore as useZustand } from 'zustand';

export interface AuthState {
  user: JwtUser | null
  setAuth: (user: JwtUser) => void
  clearAuth: () => void
}

export type AuthStore = StoreApi<AuthState>;


export function createAuthStore(initial?: Partial<AuthState>) {
  return createStore<AuthState>((set) => ({
    user: initial?.user ?? null,
    setAuth: (user) => set({ user }),
    clearAuth: () => set({ user: null }),
  }));
}

export function createUseAuthStore(store: ReturnType<typeof createAuthStore>) {
  return function useStore<T>(selector: (s: AuthState) => T) {
    return useZustand(store, selector);
  };
}
