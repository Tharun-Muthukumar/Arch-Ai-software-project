import { describe, expect, it } from 'vitest'
import { getActiveWorkspace } from './utils'
import type { Workspace } from '../types/api'

describe('getActiveWorkspace', () => {
  const workspaces = [
    { id: 'project-a', title: 'A' },
    { id: 'project-b', title: 'B' },
  ] as Workspace[]

  it('never substitutes another project for an explicit missing id', () => {
    expect(getActiveWorkspace(workspaces, 'missing-project')).toBeNull()
    expect(getActiveWorkspace(workspaces, 'project-b')?.id).toBe('project-b')
  })

  it('uses the first project only when no project was requested', () => {
    expect(getActiveWorkspace(workspaces, null)?.id).toBe('project-a')
  })
})
