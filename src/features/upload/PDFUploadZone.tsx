import { useRef, useState } from 'react'
import { useNavigate } from 'react-router'
import { precheckPdf, useUploadPdf } from '@/api/source'
import { Button } from '@/components/ui/Button'
import { ProgressBar } from '@/components/ui/controls'
import { ErrorNotice } from '@/components/ui/ErrorNotice'
import { ko } from '@/i18n/ko'
import { cn } from '@/lib/cn'
import { formatMB } from '@/lib/format'
import { GuideSheet } from './GuideSheet'
import { UploadExpectations } from './UploadExpectations'

/**
 * PDF drop zone. Validates size/type before sending, shows upload progress,
 * then opens the new project's analysis screen.
 */
export function PDFUploadZone({ large }: { large: boolean }) {
  const navigate = useNavigate()
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragover, setDragover] = useState(false)
  const [guideOpen, setGuideOpen] = useState(false)
  const [localError, setLocalError] = useState<unknown>(null)
  const upload = useUploadPdf()
  const busy = upload.isPending

  const start = (file: File | undefined) => {
    if (!file || busy) return
    const pre = precheckPdf(file)
    if (pre) {
      setLocalError(pre)
      return
    }
    setLocalError(null)
    upload.mutate(file, {
      onSuccess: (out) => navigate(`/projects/${out.project.id}/analyze`),
    })
  }

  const error = localError ?? upload.error
  const progress = upload.progress

  return (
    <>
      <div
        role="button"
        tabIndex={0}
        aria-label={ko.upload.drop}
        onClick={() => !busy && inputRef.current?.click()}
        onKeyDown={(e) => {
          if ((e.key === 'Enter' || e.key === ' ') && !busy) {
            e.preventDefault()
            inputRef.current?.click()
          }
        }}
        onDragOver={(e) => {
          e.preventDefault()
          setDragover(true)
        }}
        onDragLeave={() => setDragover(false)}
        onDrop={(e) => {
          e.preventDefault()
          setDragover(false)
          start(e.dataTransfer.files[0])
        }}
        className={cn(
          'flex cursor-pointer flex-col items-center justify-center gap-4 rounded-xl border-2 border-dashed bg-surface px-6 text-center transition-colors',
          'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent',
          large ? 'min-h-[420px] py-12' : 'gap-2 py-4',
          dragover ? 'border-accent bg-accent/5' : 'border-line hover:border-ink-muted/40',
          busy && 'cursor-progress',
        )}
      >
        <input
          ref={inputRef}
          type="file"
          accept="application/pdf,.pdf"
          className="hidden"
          onChange={(e) => {
            start(e.target.files?.[0])
            e.target.value = ''
          }}
        />
        {busy ? (
          <div className="w-full max-w-sm space-y-2" aria-live="polite">
            <p className="text-sm font-medium">
              {progress
                ? ko.upload.uploading(formatMB(progress.loaded), formatMB(progress.total))
                : ko.upload.creating}
            </p>
            <ProgressBar value={progress ? progress.loaded / Math.max(progress.total, 1) : null} />
          </div>
        ) : (
          <div className="space-y-1">
            <p className={cn('font-semibold', large ? 'text-lg' : 'text-base')}>
              {dragover ? ko.upload.dragover : ko.upload.drop}
            </p>
            <p className="text-sm text-ink-muted">
              또는{' '}
              <Button
                variant="secondary"
                className="mx-1 h-7"
                onClick={(e) => {
                  e.stopPropagation()
                  inputRef.current?.click()
                }}
              >
                {ko.upload.choose}
              </Button>{' '}
              · {ko.upload.limits}
            </p>
          </div>
        )}
        {large ? (
          <UploadExpectations onGuide={() => setGuideOpen(true)} />
        ) : (
          <button
            type="button"
            className="text-xs font-medium text-accent hover:underline"
            onClick={(e) => {
              e.stopPropagation()
              setGuideOpen(true)
            }}
          >
            {ko.upload.guide}
          </button>
        )}
        {error ? (
          <div className="w-full max-w-md" onClick={(e) => e.stopPropagation()}>
            <ErrorNotice error={error} />
          </div>
        ) : null}
      </div>
      <GuideSheet open={guideOpen} onOpenChange={setGuideOpen} />
    </>
  )
}
