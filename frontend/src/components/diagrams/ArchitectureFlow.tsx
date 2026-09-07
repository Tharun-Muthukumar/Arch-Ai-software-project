import { CircleHelp, Edit3, Plus, Trash2 } from 'lucide-react'
import { Link } from 'react-router-dom'
import type { ArchitectureComponent, ArchitectureOption } from '../../types/api'

interface ArchitectureFlowProps {
  architecture: ArchitectureOption
  whyHref?: (component: ArchitectureComponent) => string
  onAdd?: () => void
  onEdit?: (component: ArchitectureComponent, index: number) => void
  onDelete?: (component: ArchitectureComponent, index: number) => void
}

export function ArchitectureFlow({ architecture, whyHref, onAdd, onEdit, onDelete }: ArchitectureFlowProps) {
  return (
    <div className="panel">
      <div className="mb-4 flex items-start justify-between gap-3">
        <div>
          <span className="status-chip status-accent">{architecture.style}</span>
          <h3 className="mt-2 text-lg font-semibold">{architecture.name}</h3>
        </div>
        {onAdd ? <button type="button" className="button-secondary gap-2 px-3 py-2" onClick={onAdd}><Plus className="h-4 w-4" />Add component</button> : null}
      </div>
      <div className="mb-4">
        <p className="mt-1 text-sm" style={{ color: 'var(--text-muted)' }}>
          {architecture.overview}
        </p>
      </div>

      <div className="space-y-3">
        {architecture.components.map((component, index) => (
          <div
            key={component.name}
            className="editor-row items-start p-3"
            style={{ borderColor: 'var(--card-border)' }}
          >
            <div className="flex items-start gap-3">
              <div className="id-badge">CMP-{String(index + 1).padStart(2, '0')}</div>
              <div className="min-w-0 flex-1">
                <div className="flex items-start justify-between gap-2">
                  <h4 className="font-medium">{component.name}</h4>
                  {onEdit && onDelete ? (
                    <div className="row-actions">
                      <button type="button" className="icon-button" title="Edit component" aria-label={`Edit ${component.name}`} onClick={() => onEdit(component, index)}><Edit3 className="h-3.5 w-3.5" /></button>
                      <button type="button" className="icon-button danger-hover" title="Delete component" aria-label={`Delete ${component.name}`} onClick={() => onDelete(component, index)}><Trash2 className="h-3.5 w-3.5" /></button>
                    </div>
                  ) : null}
                </div>
                <p className="mt-1 text-sm" style={{ color: 'var(--text-muted)' }}>
                  {component.responsibility}
                </p>
                <div className="mt-2 flex flex-wrap gap-1">
                  {component.technologies.map((technology) => (
                    <span
                      key={technology}
                      className="rounded border px-1.5 py-0.5 text-xs"
                      style={{ borderColor: 'var(--card-border)', color: 'var(--text-muted)' }}
                    >
                      {technology}
                    </span>
                  ))}
                </div>
                {whyHref && (
                  <Link
                    to={whyHref(component)}
                    className="mt-3 inline-flex items-center gap-1.5 text-xs font-medium text-amber-300 hover:text-amber-200"
                  >
                    <CircleHelp className="h-3.5 w-3.5" />
                    Why does this exist?
                  </Link>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>

      <div className="mt-4 rounded-lg border p-3" style={{ borderColor: 'var(--card-border)' }}>
        <div className="text-xs font-medium" style={{ color: 'var(--text-muted)' }}>Data flow</div>
        <ul className="mt-2 space-y-1 text-sm">
          {architecture.data_flow.map((step) => (
            <li key={step}>{step}</li>
          ))}
        </ul>
      </div>
    </div>
  )
}
