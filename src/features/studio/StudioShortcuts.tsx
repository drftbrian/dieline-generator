import { useShortcut } from '@/lib/shortcuts'
import { useCanvasStore } from '@/stores/useCanvasStore'
import { useUiStore } from '@/stores/useUiStore'

/** Global Studio shortcuts. Canvas zoom/pan keys live in the Viewport. */
export function StudioShortcuts() {
  const c = useCanvasStore.getState
  useShortcut({ key: 'Digit1' }, () => c().setView('source'))
  useShortcut({ key: 'Digit2' }, () => c().setView('flat'))
  useShortcut({ key: 'Digit3' }, () => c().setView('merge'))
  useShortcut({ key: 'f' }, () => c().setFullscreen(!c().fullscreen))
  useShortcut({ key: '[' }, () => useUiStore.getState().toggleLeftPanel())
  useShortcut({ key: 'h' }, () => useUiStore.getState().toggleHistory())
  return null
}
