import { useMemo, useState } from 'react'
import type { Project } from '@/api/types'
import { Select } from '@/components/ui/controls'
import { ko } from '@/i18n/ko'
import { ProjectCard } from './ProjectCard'

type Sort = 'recent' | 'name'

export function ProjectGrid({ projects }: { projects: Project[] }) {
  const [sort, setSort] = useState<Sort>('recent')
  const sorted = useMemo(
    () =>
      [...projects].sort((a, b) =>
        sort === 'name' ? a.name.localeCompare(b.name, 'ko') : b.updated_at.localeCompare(a.updated_at),
      ),
    [projects, sort],
  )
  return (
    <section>
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold">{ko.dashboard.recent}</h2>
        <label className="flex items-center gap-2 text-xs text-ink-muted">
          {ko.dashboard.sortLabel}
          <Select<Sort>
            label={ko.dashboard.sortLabel}
            value={sort}
            onChange={setSort}
            options={[
              { value: 'recent', label: ko.dashboard.sortRecent },
              { value: 'name', label: ko.dashboard.sortName },
            ]}
          />
        </label>
      </div>
      <div className="grid grid-cols-[repeat(auto-fill,minmax(200px,1fr))] gap-4">
        {sorted.map((p) => (
          <ProjectCard key={p.id} project={p} />
        ))}
      </div>
    </section>
  )
}
