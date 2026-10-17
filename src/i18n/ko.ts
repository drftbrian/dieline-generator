// All UI copy lives under src/i18n/ko/ so a second language can be added later.
import { common } from './ko/common'
import { entry } from './ko/entry'
import { figma } from './ko/figma'
import { studio } from './ko/studio'

export const ko = { ...common, ...entry, studio, figma } as const
