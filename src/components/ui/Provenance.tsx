import { cn } from '@/lib/cn'
import { Tooltip } from './overlays'

/** Provenance badges: same symbols and colors everywhere in the app. */
export type ProvenanceKind =
  | 'pdf'
  | 'extracted'
  | 'user_confirmed'
  | 'user_setting'
  | 'claude_inferred'
  | 'generated'
  | 'default'
  | 'estimate'

const BADGES: Record<ProvenanceKind, { label: string; className: string; title: string }> = {
  pdf: { label: 'PDF', className: 'text-prov-source border-prov-source/40', title: '원본 PDF에서 읽은 값' },
  extracted: { label: '추출', className: 'text-prov-source border-prov-source/40', title: 'PDF를 분석해 얻은 값' },
  user_confirmed: { label: '확정', className: 'text-prov-user border-prov-user/40', title: '사용자가 확정한 값' },
  user_setting: { label: '●', className: 'text-prov-user border-prov-user/40', title: '사용자가 설정한 값' },
  claude_inferred: { label: '◆ AI', className: 'text-prov-ai border-prov-ai/40', title: 'Claude가 추론한 값 — 확인 후 사용하세요' },
  generated: { label: '✦', className: 'text-prov-generated border-prov-generated/40', title: 'AI 생성 결과' },
  default: { label: '○', className: 'text-ink-muted border-line', title: '기본값' },
  estimate: { label: '추정 ✎', className: 'text-prov-estimate border-prov-estimate/40', title: '추정값 — 실제 사양으로 수정하세요' },
}

export function ProvenanceBadge({ kind, className }: { kind: ProvenanceKind; className?: string }) {
  const b = BADGES[kind]
  return (
    <Tooltip content={b.title}>
      <span className={cn('inline-flex items-center rounded border px-1 text-[10px] leading-4 font-medium', b.className, className)}>
        {b.label}
      </span>
    </Tooltip>
  )
}
