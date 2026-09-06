import { CircleHelp } from 'lucide-react'
import { Link } from 'react-router-dom'
import type { ArchitectureComponent, ArchitectureOption } from '../../types/api'

interface ArchitectureFlowProps {
  architecture: ArchitectureOption
  whyHref?: (component: ArchitectureComponent) => string
}

export function ArchitectureFlow({ architecture, whyHref }: ArchitectureFlowProps) {
  return (
    <div className="panel">
      <div className="mb-4">
        <span className="pill">{architecture.style}</span>
        <h3 className="mt-2 text-lg font-semibold">{architecture.name}</h3>
        <p className="mt-1 text-sm" style={{ color: 'var(--text-muted)' }}>
          {architecture.overview}
        </p>
      </div>

      <div className="space-y-3">
        {architecture.components.map((component, index) => (
          <div
            key={component.name}
            className="rounded-lg border p-3"
            style={{ borderColor: 'var(--card-border)' }}
          >
            <div className="flex items-start gap-3">
              <div
                className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-semibold"
                style={{ background: 'var(--brand-soft)', color: 'var(--brand-strong)' }}
              >
                {index + 1}
              </div>
              <div className="min-w-0 flex-1">
                <h4 className="font-medium">{component.name}</h4>
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
