import { useState } from 'react'
import { useNavigate } from 'react-router'
import { useFigmaStatus, useImportFigma } from '@/api/figma'
import { Button } from '@/components/ui/Button'
import { ErrorNotice } from '@/components/ui/ErrorNotice'
import { Spinner } from '@/components/ui/Spinner'
import { ko } from '@/i18n/ko'
import { cn } from '@/lib/cn'

/** Paste a Figma frame link: the main way to start a project. */
export function FigmaLinkImport({ large = false }: { large?: boolean }) {
  const t = ko.figma
  const navigate = useNavigate()
  const status = useFigmaStatus()
  const importFigma = useImportFigma()
  const [url, setUrl] = useState('')
  const disabled = status.data?.configured === false

  const submit = () => {
    const link = url.trim()
    if (!link || importFigma.isPending) return
    importFigma.mutate(link, { onSuccess: (out) => navigate(`/projects/${out.project.id}/analyze`) })
  }

  return (
    <section className={cn('rounded-xl border-2 border-accent/30 bg-surface', large ? 'px-8 py-12' : 'p-5')}>
      <div className="mb-3 space-y-1">
        <h2 className={cn('font-semibold', large ? 'text-lg' : 'text-base')}>{t.importTitle}</h2>
        <p className="text-sm text-ink-muted">{t.importBody}</p>
        <p className="text-xs text-ink-muted">{t.importHint}</p>
      </div>
      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault()
          submit()
        }}
      >
        <input
          type="url"
          aria-label={t.importTitle}
          placeholder={t.placeholder}
          value={url}
          disabled={disabled || importFigma.isPending}
          onChange={(e) => {
            setUrl(e.target.value)
            importFigma.reset()
          }}
          className="h-9 min-w-0 flex-1 rounded-md border border-line bg-surface px-3 text-sm outline-none focus-visible:border-accent disabled:opacity-60"
        />
        <Button type="submit" variant="primary" disabled={disabled || !url.trim() || importFigma.isPending}>
          {importFigma.isPending ? (
            <>
              <Spinner className="size-3.5" /> {t.importing}
            </>
          ) : (
            t.importButton
          )}
        </Button>
      </form>
      {disabled && <p className="mt-2 text-xs text-amber-700">{t.notConfigured}</p>}
      {importFigma.error && <ErrorNotice error={importFigma.error} className="mt-2" />}
    </section>
  )
}
