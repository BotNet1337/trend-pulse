import type { AlertItem } from "@/entities/viewer";
import { createStore, type StoreApi } from "zustand";
import { useStore as useZustand } from "zustand";

export interface AlertState {
  items: AlertItem[];
  add: (item: AlertItem) => void;
  remove: (id: string) => void;
  unsubscribe: (item: AlertItem) => () => void;
}

export type AlertStore = StoreApi<AlertState>;

export function createAlertStore(): AlertStore {
  const timers = new Map<string, ReturnType<typeof setTimeout>>();

  const DEFAULT_DURATION = 5000;


  return createStore<AlertState>((set, get) => {
    return {
      items: [],
      unsubscribe: (item: AlertItem) => {
        const id = item.id;
        const timerId = timers.get(id);

        if (timerId) {
          clearTimeout(timerId);
          timers.delete(id);
        }

        return () => {
          const timer = timers.get(id);
          if (timer) {
            clearTimeout(timer);
            timers.delete(id);
          }
        };
      },
      add: (item) => {
        get().unsubscribe(item);

        set((state) => ({
          items: [...state.items, item],
        }));

        const timeoutId = setTimeout(() => {
          get().remove(item.id);
        }, DEFAULT_DURATION);

        timers.set(item.id, timeoutId);
      },
      remove: (id) => {
        const timerId = timers.get(id);
        if (timerId) {
          clearTimeout(timerId);
          timers.delete(id);
        }

        set((state) => ({
          items: state.items.filter((i) => i.id !== id),
        }));
      },
    };
  });
}

export function createUseAlertStore(store: AlertStore) {
  return function useStore<T>(selector: (s: AlertState) => T) {
    return useZustand(store, selector);
  };
}
