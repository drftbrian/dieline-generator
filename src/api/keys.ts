// Query key factory — one place to look when invalidating.
export const keys = {
  health: ['health'] as const,
  projects: ['projects'] as const,
  project: (id: string) => ['project', id] as const,
  spec: (id: string) => ['spec', id] as const,
  references: (id: string) => ['references', id] as const,
  history: (id: string) => ['history', id] as const,
  job: (id: string) => ['job', id] as const,
  assets: (id: string) => ['assets', id] as const,
}
