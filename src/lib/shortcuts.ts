import { useEffect, useLayoutEffect, useRef } from 'react'

/** True while the user is typing somewhere a shortcut must not fire. */
export function isTyping(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null
  if (!el) return false
  const tag = el.tagName
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || el.isContentEditable
}

type Combo = {
  key: string // KeyboardEvent.key, compared case-insensitively ("1", "g", "Enter", "ArrowLeft")
  mod?: boolean // Cmd on macOS, Ctrl elsewhere
  shift?: boolean
  alt?: boolean
  /** Fire even while typing in a field (e.g. Cmd+Enter in the instruction box). */
  allowInInput?: boolean
}

/**
 * Register a keyboard shortcut. Plain-key shortcuts are ignored while typing.
 * Pass `enabled: false` to scope a shortcut to a screen state.
 */
export function useShortcut(combo: Combo, handler: (e: KeyboardEvent) => void, enabled = true) {
  const ref = useRef(handler)
  useLayoutEffect(() => {
    ref.current = handler
  })
  const { key, mod = false, shift = false, alt = false, allowInInput = false } = combo
  useEffect(() => {
    if (!enabled) return
    const onKey = (e: KeyboardEvent) => {
      const m = e.metaKey || e.ctrlKey
      if (m !== mod || e.shiftKey !== shift || e.altKey !== alt) return
      if (e.key.toLowerCase() !== key.toLowerCase() && e.code !== key) return
      if (!allowInInput && isTyping(e.target)) return
      e.preventDefault()
      ref.current(e)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [key, mod, shift, alt, allowInInput, enabled])
}

export const MOD_LABEL = typeof navigator !== 'undefined' && /Mac/.test(navigator.platform) ? '⌘' : 'Ctrl'
