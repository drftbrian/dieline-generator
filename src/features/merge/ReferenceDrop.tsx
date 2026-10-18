import { useRef, useState } from 'react'
import { ApiError } from '@/api/client'
import { ACCEPTED_IMAGE_TYPES, MAX_REFERENCE_MB, useUploadReference } from '@/api/references'
import type { Reference } from '@/api/types'
import { ErrorNotice } from '@/components/ui/ErrorNotice'
import { Spinner } from '@/components/ui/Spinner'
import { ko } from '@/i18n/ko'
import { cn } from '@/lib/cn'

const t = ko.studio.merge

function precheck(file: File): ApiError | null {
  if (!ACCEPTED_IMAGE_TYPES.includes(file.type)) {
    return new ApiError(400, { code: 'REFERENCE_FORMAT', message: '지원하지 않는 이미지 형식입니다.', hint: t.formats })
  }
  if (file.size > MAX_REFERENCE_MB * 1024 * 1024) {
    return new ApiError(413, {
      code: 'REFERENCE_TOO_LARGE',
      message: `이미지가 ${MAX_REFERENCE_MB}MB를 넘습니다.`,
      hint: '더 작은 이미지를 사용해주세요.',
    })
  }
  return null
}

/** Drop (or pick) an image: the reference photo, or the AI photo to correct. */
export function ImageDrop({
  current,
  pending,
  error,
  label,
  onFile,
}: {
  current: { image_url: string; filename: string } | null
  pending: boolean
  error: unknown
  label: string
  onFile: (file: File) => void
}) {
  const input = useRef<HTMLInputElement>(null)
  const [over, setOver] = useState(false)
  const [localError, setLocalError] = useState<ApiError | null>(null)

  const add = (file: File | undefined) => {
    if (!file || pending) return
    const pre = precheck(file)
    setLocalError(pre)
    if (!pre) onFile(file)
  }

  return (
    <div className="space-y-2">
      <div
        role="button"
        tabIndex={0}
        aria-label={label}
        onClick={() => input.current?.click()}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault()
            input.current?.click()
          }
        }}
        onDragOver={(e) => {
          if (!e.dataTransfer.types.includes('Files')) return
          e.preventDefault()
          setOver(true)
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault()
          setOver(false)
          add(e.dataTransfer.files[0])
        }}
        className={cn(
          'relative cursor-pointer overflow-hidden rounded-lg border-2 border-dashed text-center text-xs transition-colors',
          'focus-visible:outline-2 focus-visible:outline-accent',
          over ? 'border-accent bg-accent/5' : 'border-line hover:border-accent/50',
        )}
      >
        {current ? (
          <>
            <img src={current.image_url} alt={current.filename} className="max-h-56 w-full bg-canvas object-contain" />
            <p className="truncate border-t border-line px-2 py-1.5 text-ink-muted">
              {current.filename} · <span className="text-accent">{t.replace}</span>
            </p>
          </>
        ) : (
          <div className="px-3 py-8">
            <p className="text-ink">{label}</p>
            <p className="mt-1 text-accent">[{t.pick}]</p>
            <p className="mt-1 text-ink-muted">{t.formats}</p>
          </div>
        )}
        {pending && (
          <div className="absolute inset-0 flex items-center justify-center gap-1.5 bg-surface/80 text-ink-muted">
            <Spinner className="size-3" /> {t.uploading}
          </div>
        )}
        <input
          ref={input}
          type="file"
          accept={ACCEPTED_IMAGE_TYPES.join(',')}
          hidden
          onChange={(e) => {
            add(e.target.files?.[0])
            e.target.value = ''
          }}
        />
      </div>
      <ErrorNotice error={localError ?? error} />
    </div>
  )
}

/** Drop (or pick) the one reference photo for the next merge. */
export function ReferenceDrop({
  projectId,
  current,
  onUploaded,
}: {
  projectId: string
  current: Reference | null
  onUploaded: (ref: Reference) => void
}) {
  const upload = useUploadReference(projectId)
  return (
    <ImageDrop
      current={current}
      pending={upload.isPending}
      error={upload.error}
      label={t.drop}
      onFile={(file) => upload.mutate(file, { onSuccess: onUploaded })}
    />
  )
}
