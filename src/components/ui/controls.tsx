import { Slider as SliderPrimitive } from 'radix-ui'
import { type ButtonHTMLAttributes, type ReactNode, useState } from 'react'
import { cn } from '@/lib/cn'

export function IconButton({
  label,
  className,
  active,
  type = 'button',
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { label: string; active?: boolean }) {
  return (
    <button
      type={type}
      aria-label={label}
      title={label}
      aria-pressed={active}
      className={cn(
        'inline-flex size-8 items-center justify-center rounded-md text-sm text-ink-muted',
        'hover:bg-canvas hover:text-ink disabled:pointer-events-none disabled:opacity-40',
        'focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent',
        active && 'bg-canvas text-ink',
        className,
      )}
      {...props}
    />
  )
}

export function SegmentedControl<T extends string>({
  value,
  options,
  onChange,
  size = 'md',
  label,
}: {
  value: T
  options: { value: T; label: ReactNode; disabled?: boolean; title?: string }[]
  onChange: (v: T) => void
  size?: 'sm' | 'md'
  label: string
}) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex rounded-md border border-line bg-canvas p-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="radio"
          aria-checked={o.value === value}
          disabled={o.disabled}
          title={o.title}
          onClick={() => onChange(o.value)}
          className={cn(
            'rounded px-2.5 font-medium whitespace-nowrap transition-colors',
            size === 'sm' ? 'h-6 text-xs' : 'h-7 text-sm',
            o.value === value ? 'bg-surface text-ink shadow-sm' : 'text-ink-muted hover:text-ink',
            'disabled:cursor-not-allowed disabled:opacity-40',
            'focus-visible:outline-2 focus-visible:outline-accent',
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}

/** Slider: arrow keys move 1 step, Shift+arrow 10. */
export function Slider({
  value,
  onChange,
  min = 0,
  max = 100,
  step = 1,
  label,
  disabled,
  onCommit,
}: {
  value: number
  onChange: (v: number) => void
  /** Called once when a drag or key press ends (for undoable edits). */
  onCommit?: (v: number) => void
  min?: number
  max?: number
  step?: number
  label: string
  disabled?: boolean
}) {
  return (
    <SliderPrimitive.Root
      className="relative flex h-5 w-full touch-none items-center select-none"
      value={[value]}
      min={min}
      max={max}
      step={step}
      disabled={disabled}
      onValueChange={(v) => onChange(v[0] ?? value)}
      onValueCommit={onCommit ? (v) => onCommit(v[0] ?? value) : undefined}
      onKeyDown={(e) => {
        if (e.shiftKey && ['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(e.key)) {
          e.preventDefault()
          const dir = e.key === 'ArrowLeft' || e.key === 'ArrowDown' ? -1 : 1
          const next = Math.min(max, Math.max(min, value + dir * step * 10))
          onChange(next)
          onCommit?.(next)
        }
      }}
    >
      <SliderPrimitive.Track className="relative h-1 grow rounded-full bg-line">
        <SliderPrimitive.Range className="absolute h-full rounded-full bg-accent" />
      </SliderPrimitive.Track>
      <SliderPrimitive.Thumb
        aria-label={label}
        className="block size-3.5 rounded-full border border-accent bg-surface shadow focus-visible:outline-2 focus-visible:outline-accent"
      />
    </SliderPrimitive.Root>
  )
}

/** Number input that commits on blur/Enter and clamps to range. */
export function NumberField({
  value,
  onChange,
  min,
  max,
  step = 1,
  suffix,
  label,
  className,
}: {
  value: number
  onChange: (v: number) => void
  min: number
  max: number
  step?: number
  suffix?: string
  label: string
  className?: string
}) {
  const [draft, setDraft] = useState(String(value))
  // Reset the draft when the value changes from outside (React "adjust state on prop change").
  const [seen, setSeen] = useState(value)
  if (seen !== value) {
    setSeen(value)
    setDraft(String(value))
  }
  const commit = () => {
    const n = Number(draft)
    if (Number.isFinite(n)) onChange(Math.min(max, Math.max(min, Math.round(n / step) * step)))
    else setDraft(String(value))
  }
  return (
    <label className={cn('inline-flex h-7 items-center rounded-md border border-line bg-surface px-2 text-sm', className)}>
      <input
        aria-label={label}
        inputMode="decimal"
        className="w-14 bg-transparent text-right tabular-nums outline-none"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === 'Enter') commit()
          if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
            e.preventDefault()
            const d = (e.key === 'ArrowUp' ? 1 : -1) * step * (e.shiftKey ? 10 : 1)
            onChange(Math.min(max, Math.max(min, Math.round((value + d) / step) * step)))
          }
        }}
      />
      {suffix && <span className="ml-1 text-xs text-ink-muted">{suffix}</span>}
    </label>
  )
}

export function ColorField({
  value,
  onChange,
  label,
}: {
  value: string
  onChange: (v: string) => void
  label: string
}) {
  const [draft, setDraft] = useState(value)
  const [seen, setSeen] = useState(value)
  if (seen !== value) {
    setSeen(value)
    setDraft(value)
  }
  const commit = () => {
    const v = draft.startsWith('#') ? draft : `#${draft}`
    if (/^#[0-9a-fA-F]{6}$/.test(v)) onChange(v.toUpperCase())
    else setDraft(value)
  }
  return (
    <div className="inline-flex h-7 items-center gap-1.5 rounded-md border border-line bg-surface pr-2 pl-1">
      <input
        type="color"
        aria-label={label}
        value={value}
        onChange={(e) => onChange(e.target.value.toUpperCase())}
        className="size-5 cursor-pointer rounded border-0 bg-transparent p-0"
      />
      <input
        aria-label={`${label} HEX`}
        className="w-16 bg-transparent font-mono text-xs uppercase outline-none"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => e.key === 'Enter' && commit()}
      />
    </div>
  )
}

export function Select<T extends string>({
  value,
  onChange,
  options,
  label,
  className,
}: {
  value: T | ''
  onChange: (v: T) => void
  options: { value: T; label: string }[]
  label: string
  className?: string
}) {
  return (
    <select
      aria-label={label}
      value={value}
      onChange={(e) => onChange(e.target.value as T)}
      className={cn(
        'h-7 rounded-md border border-line bg-surface px-2 text-sm',
        'focus-visible:outline-2 focus-visible:outline-accent',
        className,
      )}
    >
      {value === '' && <option value="">선택</option>}
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  )
}

export function ProgressBar({ value, className }: { value: number | null; className?: string }) {
  return (
    <div className={cn('h-1 w-full overflow-hidden rounded-full bg-line', className)} role="progressbar"
      aria-valuenow={value === null ? undefined : Math.round(value * 100)} aria-valuemin={0} aria-valuemax={100}>
      {value === null ? (
        <div className="h-full w-1/3 animate-pulse rounded-full bg-accent" />
      ) : (
        <div className="h-full rounded-full bg-accent transition-[width]" style={{ width: `${value * 100}%` }} />
      )}
    </div>
  )
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn('animate-pulse rounded bg-line/70', className)} />
}

export function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className="rounded border border-line bg-canvas px-1 font-mono text-[11px] text-ink-muted">{children}</kbd>
  )
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-1 p-6 text-center">
      <p className="text-sm font-medium">{title}</p>
      {children && <div className="text-xs text-ink-muted">{children}</div>}
    </div>
  )
}
