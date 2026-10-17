import { useEffect } from 'react'
import { cn } from '@/lib/cn'
import { type Toast, useToastStore } from '@/stores/useToastStore'

const tones: Record<NonNullable<Toast['tone']>, string> = {
  neutral: 'border-line',
  success: 'border-emerald-300',
  warning: 'border-amber-300',
  danger: 'border-red-300',
}

function ToastItem({ t }: { t: Toast }) {
  const dismiss = useToastStore((s) => s.dismiss)
  useEffect(() => {
    if (!t.duration) return
    const id = setTimeout(() => dismiss(t.id), t.duration)
    return () => clearTimeout(id)
  }, [t, dismiss])
  return (
    <div className={cn('pointer-events-auto flex items-center gap-3 rounded-lg border bg-surface px-4 py-3 text-sm shadow-lg', tones[t.tone ?? 'neutral'])}>
      <span className="flex-1">{t.message}</span>
      {t.actions?.map((a) => (
        <button
          key={a.label}
          type="button"
          className="font-medium text-accent hover:underline"
          onClick={() => {
            a.onClick()
            dismiss(t.id)
          }}
        >
          {a.label}
        </button>
      ))}
      <button type="button" aria-label="닫기" className="text-ink-muted hover:text-ink" onClick={() => dismiss(t.id)}>
        ✕
      </button>
    </div>
  )
}

/** Toast region; status messages are announced politely to screen readers. */
export function Toaster() {
  const toasts = useToastStore((s) => s.toasts)
  return (
    <div aria-live="polite" className="pointer-events-none fixed bottom-36 left-1/2 z-50 flex w-[min(92vw,520px)] -translate-x-1/2 flex-col gap-2">
      {toasts.map((t) => (
        <ToastItem key={t.id} t={t} />
      ))}
    </div>
  )
}
