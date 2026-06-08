import { createStore, type StoreApi } from 'zustand/vanilla';
import { useStore as useZustand } from 'zustand';

export interface RootState {
  _placeholder?: never;
}

export type RootStore = StoreApi<RootState>;


export function createRootStore(initial?: Partial<RootState>) {
  return createStore<RootState>(() => ({
    _placeholder: initial?._placeholder,
  }));
}

export function createUseStore(store: ReturnType<typeof createRootStore>) {
  return function useStore<T>(selector: (s: RootState) => T) {
    return useZustand(store, selector);
  };
}
