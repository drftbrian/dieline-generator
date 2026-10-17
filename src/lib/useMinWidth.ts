import { useSyncExternalStore } from 'react'

export function useMinWidth(px: number): boolean {
  const query = `(min-width: ${px}px)`
  return useSyncExternalStore(
    (onChange) => {
      const mql = window.matchMedia(query)
      mql.addEventListener('change', onChange)
      return () => mql.removeEventListener('change', onChange)
    },
    () => window.matchMedia(query).matches,
  )
}
