import { useState } from 'react'
import { ApiError } from '@/api/client'
import { useInterpretEnhance, useStartEnhance } from '@/api/generate'
import { useReferences } from '@/api/references'
import type { EnhanceSpec, PromptOperation, Version } from '@/api/types'
import { Button } from '@/components/ui/Button'
import { ErrorNotice } from '@/components/ui/ErrorNotice'
import { Spinner } from '@/components/ui/Spinner'
import { VersionError } from '@/features/studio/StepPanel'
import { isEnhanceable } from '@/features/studio/versions'
import { ko } from '@/i18n/ko'
import { cn } from '@/lib/cn'
import { useCanvasStore } from '@/stores/useCanvasStore'
import { useEnhanceDraft } from '@/stores/useEnhanceDraftStore'

const t = ko.studio.flat.enhance

const MAX_PROMPT = 1000
const pct = (x: number) => `${Math.round(x * 100)}%`
const linkClass =
  'inline-flex h-8 flex-1 items-center justify-center rounded-md border border-line bg-surface px-2 text-xs font-medium hover:bg-canvas focus-visible:outline-2 focus-visible:outline-accent'

/** The server's EnhanceSpec defaults: only values that differ from these are worth showing. */
const SPEC_DEFAULTS: EnhanceSpec = {
  material_detail: 0.5,
  paper_texture: 0.5,
  lighting_softness: 0.5,
  lighting_direction: 'overhead',
  fold_depth_appearance: 0,
  fold_shadow: 0,
  fold_highlight: 0,
  edge_shading: 0,
  contact_shadow: 0,
  overall_strength: 1,
}
const APPEARANCE = new Set(['paper_material', 'lighting', 'shadows', 'fold_appearance', 'edge_appearance'])

/** A prompt the server refused (or would refuse): what was protected, and whether a safe part remains. */
type Blocked = {
  message: string
  hint: string | null
  forbidden: PromptOperation[]
  canRunAllowedOnly: boolean
  allowedOnly: string
}

const asOps = (x: unknown): PromptOperation[] =>
  Array.isArray(x)
    ? x.filter((o): o is PromptOperation => !!o && typeof (o as PromptOperation).text === 'string')
    : []

/** 422 PROMPT_PROTECTED from the enhance call itself: the server is authoritative. */
function blockedFromError(error: unknown): Blocked | null {
  if (!(error instanceof ApiError) || error.code !== 'PROMPT_PROTECTED') return null
  const allowed = asOps(error.details.allowed)
  const allowedOnly = typeof error.details.allowed_only_prompt === 'string' ? error.details.allowed_only_prompt : ''
  return {
    message: error.message,
    hint: error.hint,
    forbidden: asOps(error.details.forbidden),
    canRunAllowedOnly: allowed.length > 0,
    allowedOnly: allowedOnly || allowed.map((o) => o.text).join('. '),
  }
}

/** Why a start failed, plus a plain next step for the cases the server message doesn't cover. */
function StartError({ error }: { error: unknown }) {
  if (!error) return null
  const code = error instanceof ApiError ? error.code : null
  if (code === 'PROMPT_PROTECTED') return null // shown as <BlockedNotice>
  return (
    <div className="space-y-1">
      <ErrorNotice error={error} />
      {code === 'PROVIDER_UNAVAILABLE' && <p className="text-xs text-ink-muted">{t.noKey}</p>}
    </div>
  )
}

function StrengthSlider({ value, onChange }: { value: number; onChange: (v: number) => void }) {
  return (
    <label className="block space-y-1">
      <span className="flex justify-between text-xs">
        <span className="font-medium">{t.strength}</span>
        <span className="tabular-nums text-ink-muted">{value}%</span>
      </span>
      <input
        type="range"
        min={0}
        max={100}
        step={5}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full accent-accent"
      />
    </label>
  )
}

/** The free-text request plus quick presets that append (never replace), capped at 1000 chars. */
function PromptEditor({
  value,
  onChange,
  readOnly,
}: {
  value: string
  onChange: (v: string) => void
  readOnly: boolean
}) {
  const append = (text: string) => {
    const base = value.replace(/\s+$/, '')
    return base ? `${base}\n${text}` : text
  }
  return (
    <div className="space-y-1.5">
      <label className="block space-y-1">
        <span className="flex justify-between text-xs">
          <span className="font-medium">{t.promptLabel}</span>
          <span
            className={cn('tabular-nums', value.length >= MAX_PROMPT ? 'text-amber-700' : 'text-ink-muted')}
            aria-live="polite"
          >
            {t.promptCount(value.length, MAX_PROMPT)}
          </span>
        </span>
        <textarea
          rows={4}
          maxLength={MAX_PROMPT}
          value={value}
          readOnly={readOnly}
          placeholder={t.promptPlaceholder}
          onChange={(e) => onChange(e.target.value)}
          className={cn(
            'block max-h-48 min-h-[5.5rem] w-full resize-y overflow-y-auto rounded-md border border-line bg-surface px-2 py-1.5 text-xs leading-relaxed [field-sizing:content]',
            'placeholder:text-ink-muted focus-visible:outline-2 focus-visible:outline-accent',
            readOnly && 'opacity-60',
          )}
        />
      </label>
      <div className="flex flex-wrap gap-1.5" role="group" aria-label={t.presetsLabel}>
        {t.presets.map((p) => {
          const full = append(p.text).length > MAX_PROMPT
          return (
            <button
              key={p.label}
              type="button"
              disabled={readOnly || full}
              title={full ? t.presetFull : p.text}
              onClick={() => onChange(append(p.text))}
              className="rounded-full border border-line bg-surface px-2.5 py-1 text-[11px] font-medium hover:bg-canvas focus-visible:outline-2 focus-visible:outline-accent disabled:pointer-events-none disabled:opacity-50"
            >
              + {p.label}
            </button>
          )
        })}
      </div>
    </div>
  )
}

/** Always visible: what the AI can never change. */
function ProtectedBox() {
  return (
    <div className="rounded-md border border-emerald-200 bg-emerald-50 px-2.5 py-2 text-[11px] text-emerald-900">
      <p className="font-medium">🔒 {t.protectedTitle}</p>
      <p className="mt-0.5">{t.protectedBody}</p>
    </div>
  )
}

function BlockedNotice({
  blocked,
  disabled,
  onRunAllowedOnly,
}: {
  blocked: Blocked
  disabled: boolean
  onRunAllowedOnly: () => void
}) {
  return (
    <div role="alert" className="space-y-2 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-800">
      <p className="font-medium">{blocked.message}</p>
      {blocked.forbidden.length > 0 && (
        <div>
          <p className="font-medium">{t.blockedList}</p>
          <ul className="mt-0.5 space-y-0.5">
            {blocked.forbidden.map((o, i) => (
              <li key={`${i}-${o.text}`} className="flex gap-1.5">
                <span className="shrink-0 rounded bg-red-100 px-1 text-[10px] font-medium">
                  {t.categories[o.category] ?? o.category}
                </span>
                <span className="break-words">“{o.text}”</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {blocked.hint && <p className="text-red-700/90">{blocked.hint}</p>}
      {blocked.canRunAllowedOnly && (
        <div className="space-y-1">
          {blocked.allowedOnly && <p className="text-red-700/90">{t.allowedOnlyPreview(blocked.allowedOnly)}</p>}
          <Button className="h-8 w-full justify-center text-xs" disabled={disabled} onClick={onRunAllowedOnly}>
            {t.runAllowedOnly}
          </Button>
        </div>
      )}
    </div>
  )
}

function Notes({ notes }: { notes: readonly string[] | null | undefined }) {
  if (!notes?.length) return null
  return (
    <div className="rounded-md border border-amber-200 bg-amber-50 px-2.5 py-2 text-[11px] text-amber-900">
      <p className="font-medium">{t.notesTitle}</p>
      <ul className="mt-0.5 list-disc space-y-0.5 pl-4">
        {notes.map((n, i) => (
          <li key={`${i}-${n}`}>{n}</li>
        ))}
      </ul>
    </div>
  )
}

/** The spec values a prompt changed from the standard enhancement. */
function SpecSummary({ spec }: { spec: EnhanceSpec }) {
  const changed = (Object.keys(SPEC_DEFAULTS) as (keyof EnhanceSpec)[]).filter((k) => {
    const v = spec[k]
    const d = SPEC_DEFAULTS[k]
    return typeof v === 'number' && typeof d === 'number' ? Math.abs(v - d) > 0.005 : v !== d
  })
  return (
    <div className="space-y-1">
      <p className="text-xs font-medium">{t.specTitle}</p>
      {changed.length === 0 ? (
        <p className="text-[11px] text-ink-muted">{t.specDefault}</p>
      ) : (
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-[11px]">
          {changed.map((k) => {
            const v = spec[k]
            return [
              <dt key={`${k}-t`} className="text-ink-muted">
                {t.specLabels[k] ?? k}
              </dt>,
              <dd key={`${k}-d`} className="tabular-nums">
                {typeof v === 'number' ? pct(v) : (t.directions[v] ?? v)}
              </dd>,
            ]
          })}
        </dl>
      )}
    </div>
  )
}

/**
 * Optional AI 보정 of a finished code render: a prompt (read and checked before anything runs),
 * a look photo and a strength; always a new version.
 */
export function EnhanceStart({
  projectId,
  source,
  busy = false,
  initialStrength = 60,
}: {
  projectId: string
  source: Version
  /** A flat job is already running. */
  busy?: boolean
  initialStrength?: number
}) {
  const start = useStartEnhance(projectId)
  const interpret = useInterpretEnhance(projectId)
  const refs = useReferences(projectId).data ?? []
  const [draft, setDraft] = useEnhanceDraft(projectId)
  const [refId, setRefId] = useState<string | null>(null)
  const [strength, setStrength] = useState(initialStrength)
  const [reading, setReading] = useState<{ notes: string[]; spec: EnhanceSpec } | null>(null)
  const [blocked, setBlocked] = useState<Blocked | null>(null)
  // A deleted reference falls back to the bundled look photo.
  const reference = refs.find((r) => r.id === refId) ?? null
  const pending = interpret.isPending || start.isPending

  const tile = (selected: boolean) =>
    cn(
      'size-12 shrink-0 overflow-hidden rounded border text-[10px] leading-tight',
      'focus-visible:outline-2 focus-visible:outline-accent',
      selected ? 'border-accent ring-2 ring-accent/30' : 'border-line',
    )

  const onPromptChange = (text: string) => {
    setDraft(text)
    // The last reading was of different text.
    setReading(null)
    setBlocked(null)
    interpret.reset()
  }

  const submit = async (confirmAllowedOnly: boolean) => {
    setBlocked(null)
    start.reset()
    const prompt = draft.trim()
    if (prompt && !confirmAllowedOnly) {
      let r
      try {
        r = await interpret.mutateAsync(prompt)
      } catch {
        return // shown below via interpret.error
      }
      setReading({ notes: r.notes, spec: r.spec })
      if (r.blocked) {
        setBlocked({
          message: r.message ?? t.protectedBody,
          hint: null,
          forbidden: r.operations.filter((o) => !o.allowed),
          canRunAllowedOnly: r.can_run_allowed_only,
          allowedOnly: r.operations
            .filter((o) => APPEARANCE.has(o.category))
            .map((o) => o.text)
            .join('. '),
        })
        return
      }
    } else if (!prompt) {
      setReading(null)
    }
    start.mutate(
      {
        sourceId: source.id,
        strength: strength / 100,
        reference_id: reference?.id ?? null,
        user_prompt: prompt || null,
        confirm_allowed_only: confirmAllowedOnly,
      },
      {
        onSuccess: () => useCanvasStore.getState().setView('flat'),
        onError: (err) => {
          const b = blockedFromError(err)
          if (b) setBlocked(b)
        },
      },
    )
  }

  return (
    <section className="space-y-3 rounded-md border border-line p-3">
      <div className="space-y-1">
        <h3 className="text-xs font-semibold">{t.sectionTitle}</h3>
        <p className="text-xs text-ink-muted">{t.sectionIntro}</p>
      </div>

      <PromptEditor value={draft} onChange={onPromptChange} readOnly={pending} />

      <div>
        <p className="mb-1 text-xs font-medium">{t.reference}</p>
        <div className="flex flex-wrap gap-1.5">
          <button
            type="button"
            title={t.fallbackRef}
            aria-pressed={!reference}
            onClick={() => setRefId(null)}
            className={cn(tile(!reference), 'bg-canvas px-0.5 text-ink-muted')}
          >
            {t.fallbackRef}
          </button>
          {refs.map((r) => (
            <button
              key={r.id}
              type="button"
              title={r.filename}
              aria-pressed={r.id === reference?.id}
              onClick={() => setRefId(r.id)}
              className={tile(r.id === reference?.id)}
            >
              <img src={r.thumb_url} alt={r.filename} className="h-full w-full object-cover" />
            </button>
          ))}
        </div>
      </div>

      <div>
        <StrengthSlider value={strength} onChange={setStrength} />
        <p className="mt-0.5 text-[11px] text-ink-muted">
          {t.strengthHint} {t.strengthZero}
        </p>
      </div>

      <ProtectedBox />

      <Button
        variant="primary"
        className="w-full justify-center"
        disabled={pending || busy}
        onClick={() => void submit(false)}
      >
        {pending ? (
          <>
            <Spinner className="size-3.5" /> {interpret.isPending ? t.checking : t.starting}
          </>
        ) : (
          t.submit
        )}
      </Button>
      <p className="text-[11px] text-ink-muted">{t.cost}</p>

      {blocked && (
        <BlockedNotice blocked={blocked} disabled={pending || busy} onRunAllowedOnly={() => void submit(true)} />
      )}
      {interpret.error && <ErrorNotice error={interpret.error} />}
      <StartError error={start.error} />
      {reading && !blocked && (
        <>
          <Notes notes={reading.notes} />
          <SpecSummary spec={reading.spec} />
        </>
      )}
    </section>
  )
}

/** A finished AI-enhanced version: before/after, prompt and spec used, free re-apply, downloads. */
export function EnhanceResult({
  projectId,
  version,
  versions,
  busy = false,
}: {
  projectId: string
  version: Version
  versions: Version[]
  busy?: boolean
}) {
  const e = version.enhancement
  const start = useStartEnhance(projectId)
  const refs = useReferences(projectId).data ?? []
  const compare = useCanvasStore((s) => s.compare)
  const [, setDraft] = useEnhanceDraft(projectId)
  const [strength, setStrength] = useState(() => Math.round((e?.strength ?? 0.6) * 100))
  const [reenhancing, setReenhancing] = useState(false)
  if (!e) return null

  const source = versions.find((v) => v.id === e.source_version_id && v.status === 'done') ?? null
  const applied = version.verify?.strength_applied ?? null
  const reference = e.reference_id ? refs.find((r) => r.id === e.reference_id) : null

  return (
    <section className="space-y-3 rounded-md border border-violet-200 bg-violet-50/40 p-3">
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="text-xs font-semibold">{t.resultTitle}</h3>
        {source && <span className="text-[11px] text-ink-muted">{t.sourceOf(source.number)}</span>}
      </div>

      <div className="grid grid-cols-2 gap-2 text-[11px]">
        <figure className="space-y-1">
          <button
            type="button"
            title={source ? t.showOriginal : t.sourceMissing}
            disabled={!source}
            onClick={() => source && useCanvasStore.getState().showVersion(source.id, 'flat')}
            className="block w-full overflow-hidden rounded border border-line bg-black focus-visible:outline-2 focus-visible:outline-accent"
          >
            <img src={source?.thumb_url ?? e.source_image_url} alt={t.original} className="aspect-square w-full object-contain" />
          </button>
          <figcaption className="text-center text-ink-muted">
            {t.original}
            {source && ` · v${source.number}`}
          </figcaption>
        </figure>
        <figure className="space-y-1">
          <div className="overflow-hidden rounded border border-accent bg-black">
            {version.thumb_url && (
              <img src={version.thumb_url} alt={t.enhanced} className="aspect-square w-full object-contain" />
            )}
          </div>
          <figcaption className="text-center font-medium">
            {t.enhanced} · v{version.number}
          </figcaption>
        </figure>
      </div>

      <label className="flex items-center gap-1.5 text-xs">
        <input type="checkbox" checked={compare} onChange={(ev) => useCanvasStore.getState().setCompare(ev.target.checked)} />
        {t.compare}
      </label>

      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs">
        <dt className="text-ink-muted">{t.requested}</dt>
        <dd className="tabular-nums">{pct(e.strength)}</dd>
        <dt className="text-ink-muted">{t.applied}</dt>
        <dd className="tabular-nums">{applied != null ? pct(applied) : '—'}</dd>
        <dt className="text-ink-muted">{t.usedReference}</dt>
        <dd className="truncate">{e.reference_id ? (reference?.filename ?? e.reference_id) : t.fallbackRef}</dd>
      </dl>
      {applied != null && applied < e.strength - 0.005 && <p className="text-[11px] text-amber-800">{t.appliedLower}</p>}

      <div className="space-y-2 border-t border-line pt-3">
        <div className="space-y-1">
          <p className="text-xs font-medium">{t.promptUsed}</p>
          <p
            className={cn(
              'max-h-32 overflow-y-auto whitespace-pre-wrap break-words rounded border border-line bg-surface px-2 py-1.5 text-[11px]',
              !e.user_prompt && 'text-ink-muted',
            )}
          >
            {e.user_prompt || t.noPrompt}
          </p>
        </div>
        {e.spec && <SpecSummary spec={e.spec} />}
        <Notes notes={e.notes} />
      </div>

      <div className="space-y-2 border-t border-line pt-3">
        <p className="text-xs font-medium">{t.reapplyTitle}</p>
        <StrengthSlider value={strength} onChange={setStrength} />
        <p className="text-[11px] text-ink-muted">{t.strengthZero}</p>
        <Button
          className="w-full justify-center"
          disabled={start.isPending || busy || !source}
          onClick={() =>
            start.mutate(
              {
                sourceId: e.source_version_id,
                strength: strength / 100,
                maps_from: version.id,
                // Same prompt as the maps it reuses. It already ran (possibly as "allowed part
                // only"), so confirm that again rather than be refused for the dropped part.
                user_prompt: e.user_prompt ?? null,
                confirm_allowed_only: true,
                // Provenance only (the maps are reused); a since-deleted photo would be refused.
                reference_id: reference?.id ?? null,
              },
              { onSuccess: () => useCanvasStore.getState().setView('flat') },
            )
          }
        >
          {start.isPending ? (
            <>
              <Spinner className="size-3.5" /> {t.starting}
            </>
          ) : (
            t.reapply
          )}
        </Button>
        <p className="text-[11px] text-ink-muted">{source ? t.reapplyHint : t.sourceMissing}</p>
        <StartError error={start.error} />
      </div>

      <div className="space-y-2 border-t border-line pt-3">
        {reenhancing && source ? (
          <>
            <div className="flex items-baseline justify-between gap-2">
              <p className="text-xs font-medium">{t.reenhanceTitle}</p>
              <button
                type="button"
                onClick={() => setReenhancing(false)}
                className="text-[11px] text-ink-muted underline hover:text-ink focus-visible:outline-2 focus-visible:outline-accent"
              >
                {t.reenhanceCancel}
              </button>
            </div>
            <EnhanceStart
              projectId={projectId}
              source={source}
              busy={busy}
              initialStrength={Math.round(e.strength * 100)}
            />
          </>
        ) : (
          <Button
            className="w-full justify-center"
            disabled={!source || !isEnhanceable(source)}
            title={source ? undefined : t.sourceMissing}
            onClick={() => {
              setDraft(e.user_prompt ?? '')
              setReenhancing(true)
            }}
          >
            {t.reenhance}
          </Button>
        )}
      </div>

      <div className="space-y-1 border-t border-line pt-3">
        <p className="text-xs font-medium">{t.download}</p>
        <div className="flex gap-2">
          {source?.download_url && (
            <a href={source.download_url} download className={linkClass}>
              ⤓ {t.downloadOriginal}
            </a>
          )}
          {version.download_url && (
            <a href={version.download_url} download className={linkClass}>
              ⤓ {t.downloadEnhanced}
            </a>
          )}
        </div>
      </div>
    </section>
  )
}

/** ENHANCE_REJECTED: the AI candidate failed a check, so nothing was delivered and v3 stays. */
export function EnhanceFailure({ version }: { version: Version }) {
  const err = version.error
  if (!err) return null
  if (err.code !== 'ENHANCE_REJECTED') {
    return (
      <div className="space-y-1">
        <VersionError version={version} />
        {err.code === 'SOURCE_OUTDATED' && <p className="text-xs text-ink-muted">{t.outdated}</p>}
      </div>
    )
  }
  const reasons = Array.isArray(err.details?.reasons) ? (err.details.reasons as unknown[]).map(String) : []
  return (
    <div role="status" className="rounded-md border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
      <p className="font-medium">{t.rejectedTitle}</p>
      <p className="mt-0.5">{t.rejectedBody}</p>
      {reasons.length > 0 && (
        <>
          <p className="mt-2 font-medium">{t.reasonsTitle}</p>
          <ul className="mt-0.5 list-disc space-y-0.5 pl-4">
            {reasons.map((r) => (
              <li key={r}>{t.reasons[r] ?? r}</li>
            ))}
          </ul>
        </>
      )}
    </div>
  )
}
