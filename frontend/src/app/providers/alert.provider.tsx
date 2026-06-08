import type { AlertStore } from "@/app/stores/alert.store"
import { AlertStoreProvider } from "./alert.context"
import { Alert } from "@/entities/viewer/ui"
import { useAlertStore } from "./use-alert-store"

interface AlertProviderProps {
  children: React.ReactNode
  store: AlertStore
}

function AlertList() {
  const alertStore = useAlertStore()
  const items = alertStore((state) => state.items)
  const remove = alertStore((state) => state.remove)

  return (
    <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 w-full max-w-sm">
      {items.map((item) => (
        <div
          key={item.id}
          className="transition-all duration-300 ease-in-out opacity-100 translate-x-0"
        >
          <Alert item={item} onRemove={remove} />
        </div>
      ))}
    </div>
  )
}

export function AlertProvider({ children, store }: AlertProviderProps) {
  return (
    <AlertStoreProvider store={store}>
      {children}
      <AlertList />
    </AlertStoreProvider>
  )
}

