export const debug = (...args: unknown[]) => {
  if (!import.meta.env?.DEV) {
    return
  }

   
  console.debug(...args)
}


