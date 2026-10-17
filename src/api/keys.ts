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
  finishingCatalog: ['finishing-catalog'] as const,
  finishing: (id: string) => ['finishing', id] as const,
  finishingPreview: (id: string, versionId: string, revision: number, light: string) =>
    ['finishing-preview', id, versionId, revision, light] as const,
  finishingSweep: (id: string, versionId: string, revision: number, light: string) =>
    ['finishing-sweep', id, versionId, revision, light] as const,
  finishingWarnings: (id: string, revision: number) => ['finishing-warnings', id, revision] as const,
}
