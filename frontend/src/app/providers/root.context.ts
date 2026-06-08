import { createContext } from 'react'
import type { RootState } from '@/app/stores/app.store'

export type UseRoot = <T>(selector: (state: RootState) => T) => T

export const RootContext = createContext<UseRoot | null>(null)


