import type { ReactNode } from 'react'
import { ApiError } from '@/api/client'
import { cn } from '@/lib/cn'

/** Error copy always says what happened and what to do next. */
export function ErrorNotice({
  error,
  className,
  actions,
}: {
  error: unknown
  className?: string
  actions?: ReactNode
}) {
  if (!error) return null
  const message = error instanceof ApiError ? error.message : '문제가 발생했습니다.'
  const hint = error instanceof ApiError ? error.hint : '다시 시도해주세요.'
  return (
    <div role="alert" className={cn('rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800', className)}>
      <p className="font-medium">{message}</p>
      {hint && <p className="mt-0.5 text-red-700/90">{hint}</p>}
      {actions && <div className="mt-2 flex gap-2">{actions}</div>}
    </div>
  )
}
