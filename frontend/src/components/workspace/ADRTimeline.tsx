import { useState } from 'react'
import { Download, RotateCcw } from 'lucide-react'
import { exportAdrs } from '../../lib/api'
import { downloadBlob } from '../../lib/utils'
import type { ArchitectureDecisionRecord, Workspace } from '../../types/api'

interface TimelineEntry {
  adr: ArchitectureDecisionRecord
  snapshot: Workspace
}

interface ADRTimelineProps {
  entries: TimelineEntry[]
  activeIndex: number
  onSelect: (index: number) => void
}

export function ADRTimeline({ entries, activeIndex, onSelect }: ADRTimelineProps) {
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [isExporting, setIsExporting] = useState(false)

  const toggleExpand = (id: string) => {
    setExpandedId(expandedId === id ? null : id)
  }

  const handleExport = async () => {
    if (!entries.length) return
    setIsExporting(true)
    try {
      const adrs = entries.map((e) => e.adr)
      const blob = await exportAdrs({ adrs })
      downloadBlob(blob, 'architecture-decision-records.zip')
    } catch {
      // Silently ignore export failures
    } finally {
      setIsExporting(false)
    }
  }

  if (!entries.length) return null

  return (
    <div className="panel">
      <div className="flex items-center justify-between gap-3">
        <div>
          <span className="pill">Decision history</span>
          <h3 className="mt-2 font-semibold">Architecture timeline</h3>
        </div>
        <button
          type="button"
          onClick={() => void handleExport()}
          disabled={isExporting}
          className="button-secondary flex items-center gap-1.5 text-xs"
        >
          <Download className="h-3.5 w-3.5" />
          {isExporting ? 'Exporting…' : 'Export all as ADRs'}
        </button>
      </div>

      <div className="relative mt-5 ml-4">
        {/* Vertical line */}
        <div
          className="absolute left-0 top-0 bottom-0 w-px"
          style={{ backgroundColor: 'var(--card-border)' }}
        />

        {entries.map((entry, index) => {
          const isActive = index === activeIndex
          const isExpanded = expandedId === entry.adr.id
          const date = new Date(entry.adr.timestamp)

          return (
            <div key={entry.adr.id} className="relative pl-6 pb-6 last:pb-0">
              {/* Node dot */}
              <button
                type="button"
                onClick={() => {
                  toggleExpand(entry.adr.id)
                  onSelect(index)
                }}
                className="absolute left-0 top-1 -translate-x-1/2 z-10"
              >
                <span
                  className="block h-3 w-3 rounded-full border-2 transition"
                  style={{
                    borderColor: isActive ? 'var(--brand)' : 'var(--card-border)',
                    backgroundColor: isActive ? 'var(--brand)' : 'var(--surface)',
                  }}
                />
              </button>

              {/* Content */}
              <div>
                <button
                  type="button"
                  onClick={() => {
                    toggleExpand(entry.adr.id)
                    onSelect(index)
                  }}
                  className="text-left w-full"
                >
                  <div className="flex items-center gap-2">
                    <span
                      className="text-sm font-medium"
                      style={{ color: isActive ? 'var(--brand)' : 'var(--text)' }}
                    >
                      {entry.adr.title}
                    </span>
                    <span
                      className="text-xs"
                      style={{ color: 'var(--text-muted)' }}
                    >
                      {date.toLocaleDateString()}
                    </span>
                  </div>
                </button>

                {isExpanded && (
                  <div className="mt-2 rounded-lg border p-3 text-sm" style={{ borderColor: 'var(--card-border)', background: 'var(--surface-strong)' }}>
                    <div className="space-y-2">
                      <div>
                        <span className="font-medium">Context:</span>
                        <p className="mt-0.5" style={{ color: 'var(--text-muted)' }}>{entry.adr.context}</p>
                      </div>
                      <div>
                        <span className="font-medium">Decision:</span>
                        <p className="mt-0.5" style={{ color: 'var(--text-muted)' }}>{entry.adr.decision}</p>
                      </div>
                      <div>
                        <span className="font-medium">Consequences:</span>
                        <p className="mt-0.5" style={{ color: 'var(--text-muted)' }}>{entry.adr.consequences}</p>
                      </div>
                      {entry.adr.changed_modules.length > 0 && (
                        <div className="flex flex-wrap gap-1.5 pt-1">
                          {entry.adr.changed_modules.map((mod) => (
                            <span
                              key={mod}
                              className="rounded border px-2 py-0.5 text-xs"
                              style={{ borderColor: 'var(--card-border)', color: 'var(--text-muted)' }}
                            >
                              {mod}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                    {index > 0 && (
                      <button
                        type="button"
                        onClick={() => onSelect(index)}
                        className="button-secondary mt-3 flex items-center gap-1.5 text-xs"
                      >
                        <RotateCcw className="h-3 w-3" />
                        View this decision
                      </button>
                    )}
                  </div>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
