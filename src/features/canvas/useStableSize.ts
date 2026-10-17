import { useMemo } from 'react'

/** Same object identity while the size is unchanged (the viewport refits on identity change). */
export function useStableSize(w: number, h: number): { w: number; h: number } {
  return useMemo(() => ({ w, h }), [w, h])
}
