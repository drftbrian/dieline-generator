import { Dialog as D, Popover as P, Tooltip as T } from 'radix-ui'
import type { ReactNode } from 'react'
import { cn } from '@/lib/cn'

export function Dialog({
  open,
  onOpenChange,
  title,
  description,
  children,
  footer,
  className,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  description?: ReactNode
  children?: ReactNode
  footer?: ReactNode
  className?: string
}) {
  return (
    <D.Root open={open} onOpenChange={onOpenChange}>
      <D.Portal>
        <D.Overlay className="fixed inset-0 z-40 bg-ink/30" />
        <D.Content
          className={cn(
            'fixed top-1/2 left-1/2 z-50 w-[min(92vw,480px)] -translate-x-1/2 -translate-y-1/2',
            'rounded-xl border border-line bg-surface p-5 shadow-xl focus:outline-none',
            className,
          )}
        >
          <D.Title className="text-base font-semibold">{title}</D.Title>
          {description ? (
            <D.Description className="mt-1.5 text-sm text-ink-muted">{description}</D.Description>
          ) : (
            <D.Description className="sr-only">{title}</D.Description>
          )}
          {children && <div className="mt-4">{children}</div>}
          {footer && <div className="mt-5 flex justify-end gap-2">{footer}</div>}
        </D.Content>
      </D.Portal>
    </D.Root>
  )
}

export function SideSheet({
  open,
  onOpenChange,
  title,
  children,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  children: ReactNode
}) {
  return (
    <D.Root open={open} onOpenChange={onOpenChange}>
      <D.Portal>
        <D.Overlay className="fixed inset-0 z-40 bg-ink/20" />
        <D.Content className="fixed top-0 right-0 z-50 flex h-full w-[min(92vw,520px)] flex-col border-l border-line bg-surface shadow-xl focus:outline-none">
          <div className="flex h-12 items-center justify-between border-b border-line px-4">
            <D.Title className="font-semibold">{title}</D.Title>
            <D.Close className="rounded px-2 text-ink-muted hover:bg-canvas" aria-label="닫기">
              ✕
            </D.Close>
          </div>
          <D.Description className="sr-only">{title}</D.Description>
          <div className="flex-1 overflow-y-auto p-5">{children}</div>
        </D.Content>
      </D.Portal>
    </D.Root>
  )
}

export function Popover({
  trigger,
  children,
  open,
  onOpenChange,
  side = 'bottom',
  align = 'center',
  className,
}: {
  trigger: ReactNode
  children: ReactNode
  open?: boolean
  onOpenChange?: (o: boolean) => void
  side?: 'top' | 'bottom' | 'left' | 'right'
  align?: 'start' | 'center' | 'end'
  className?: string
}) {
  return (
    <P.Root open={open} onOpenChange={onOpenChange}>
      <P.Trigger asChild>{trigger}</P.Trigger>
      <P.Portal>
        <P.Content
          side={side}
          align={align}
          sideOffset={6}
          className={cn('z-50 rounded-lg border border-line bg-surface p-3 text-sm shadow-lg focus:outline-none', className)}
        >
          {children}
        </P.Content>
      </P.Portal>
    </P.Root>
  )
}

/** Popover anchored to an arbitrary screen point (e.g. a click on the canvas). */
export function PointPopover({
  at,
  onClose,
  children,
}: {
  at: { x: number; y: number } | null
  onClose: () => void
  children: ReactNode
}) {
  return (
    <P.Root open={!!at} onOpenChange={(o) => !o && onClose()}>
      <P.Anchor asChild>
        <span className="pointer-events-none fixed size-0" style={{ left: at?.x ?? 0, top: at?.y ?? 0 }} />
      </P.Anchor>
      <P.Portal>
        <P.Content sideOffset={8} className="z-50 rounded-lg border border-line bg-surface p-3 text-sm shadow-lg focus:outline-none">
          {children}
        </P.Content>
      </P.Portal>
    </P.Root>
  )
}

export function Tooltip({ content, children }: { content: ReactNode; children: ReactNode }) {
  if (!content) return <>{children}</>
  return (
    <T.Root delayDuration={300}>
      <T.Trigger asChild>{children}</T.Trigger>
      <T.Portal>
        <T.Content sideOffset={6} className="z-50 max-w-64 rounded-md bg-ink px-2 py-1 text-xs text-white shadow">
          {content}
        </T.Content>
      </T.Portal>
    </T.Root>
  )
}

export const TooltipProvider = T.Provider
