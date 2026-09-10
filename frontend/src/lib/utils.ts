import clsx from 'clsx'
import type { Workspace } from '../types/api'

export function cn(...values: Array<string | false | null | undefined>) {
  return clsx(values)
}

export function getActiveWorkspace(
  workspaces: Workspace[] | undefined,
  workspaceId: string | null,
) {
  if (!workspaces?.length) {
    return null
  }

  if (workspaceId) {
    return workspaces.find((workspace) => workspace.id === workspaceId) ?? null
  }
  return workspaces[0]
}

export function formatMetricName(metric: string) {
  return metric
    .replaceAll('_', ' ')
    .replace(/\b\w/g, (character) => character.toUpperCase())
}

export function downloadBlob(blob: Blob, fileName: string) {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = fileName
  anchor.click()
  URL.revokeObjectURL(url)
}

export function formatUpdatedAt(value: string) {
  return new Date(value).toLocaleString()
}

export function getErrorMessage(
  error: unknown,
  fallback = 'Something went wrong while loading this page.',
) {
  if (error instanceof Error && error.message.trim().length > 0) {
    return error.message
  }

  return fallback
}
