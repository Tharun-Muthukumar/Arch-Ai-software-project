import { AlertTriangle, Copy, Download, LoaderCircle, RefreshCw } from 'lucide-react'
import mermaid from 'mermaid'
import { useCallback, useEffect, useRef, useState } from 'react'
import { downloadBlob } from '../../lib/utils'
import type { DiagramArtifact } from '../../types/api'

interface MermaidDiagramProps {
  artifact: DiagramArtifact
}

let diagramCounter = 0

export function MermaidDiagram({ artifact }: MermaidDiagramProps) {
  const [svg, setSvg] = useState('')
  const [error, setError] = useState('')
  const [renderVersion, setRenderVersion] = useState(0)
  const [showSource, setShowSource] = useState<'hidden' | 'mermaid' | 'plantuml'>('hidden')
  const activeRender = useRef(0)

  const renderDiagram = useCallback(async () => {
    const renderAttempt = ++activeRender.current
    try {
      mermaid.initialize({
        startOnLoad: false,
        theme: 'dark',
        themeVariables: {
          background: '#1b263b',
          primaryColor: '#1e293b',
          primaryTextColor: '#f8fafc',
          primaryBorderColor: '#94a3b8',
          secondaryColor: '#172554',
          tertiaryColor: '#1f2937',
          lineColor: '#cbd5e1',
          edgeLabelBackground: '#131c2d',
          nodeBorder: '#94a3b8',
          clusterBkg: '#1e293b',
          clusterBorder: '#64748b',
          textColor: '#f8fafc',
          mainBkg: '#1e293b',
        },
        securityLevel: 'loose',
        htmlLabels: true,
      })

      // React StrictMode intentionally re-runs effects in development. A fresh
      // Mermaid ID prevents overlapping attempts from sharing temporary DOM.
      const id = `diagram-${++diagramCounter}`
      const { svg: renderedSvg } = await mermaid.render(id, artifact.mermaid)
      if (renderAttempt !== activeRender.current) return
      setSvg(renderedSvg)
      setError('')
    } catch (err) {
      if (renderAttempt !== activeRender.current) return
      console.error('Mermaid render error:', err)
      setError(`Mermaid error: ${err instanceof Error ? err.message : 'unknown'}`)
    }
  }, [artifact.mermaid, renderVersion])

  useEffect(() => {
    setSvg('')
    setError('')
    void renderDiagram()
    return () => {
      activeRender.current += 1
    }
  }, [renderDiagram])

  async function copySource(source: string) {
    await navigator.clipboard.writeText(source)
  }

  function exportPng() {
    const image = new Image()
    const svgBlob = new Blob([svg], { type: 'image/svg+xml;charset=utf-8' })
    const url = URL.createObjectURL(svgBlob)

    image.onload = () => {
      const canvas = document.createElement('canvas')
      canvas.width = image.width * 2
      canvas.height = image.height * 2
      const context = canvas.getContext('2d')
      if (!context) {
        URL.revokeObjectURL(url)
        return
      }
      context.fillStyle = '#131c2d'
      context.fillRect(0, 0, canvas.width, canvas.height)
      context.drawImage(image, 0, 0, canvas.width, canvas.height)
      canvas.toBlob((blob) => {
        if (blob) downloadBlob(blob, `${artifact.title}.png`)
      })
      URL.revokeObjectURL(url)
    }

    image.src = url
  }

  return (
    <div className="panel">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <span className="pill">{artifact.title}</span>
          <p className="mt-2 text-sm" style={{ color: 'var(--text-muted)' }}>
            {artifact.description}
          </p>
        </div>
        <div className="flex gap-1.5">
          <button
            type="button"
            onClick={() => void copySource(artifact.mermaid)}
            className="button-secondary flex items-center gap-1.5 text-xs"
          >
            <Copy className="h-3.5 w-3.5" /> Mermaid
          </button>
          <button
            type="button"
            onClick={() => void copySource(artifact.plantuml)}
            className="button-secondary flex items-center gap-1.5 text-xs"
          >
            <Copy className="h-3.5 w-3.5" /> PlantUML
          </button>
          <button
            type="button"
            onClick={exportPng}
            className="button-secondary flex items-center gap-1.5 text-xs"
          >
            <Download className="h-3.5 w-3.5" /> PNG
          </button>
        </div>
      </div>

      <div className="diagram-viewport mt-4">
        {error ? (
          <div className="diagram-state" role="alert">
            <AlertTriangle className="h-5 w-5" style={{ color: 'var(--danger)' }} />
            <div>
              <strong>Diagram could not be rendered</strong>
              <p>{error}</p>
            </div>
            <button type="button" className="button-secondary gap-2" onClick={() => setRenderVersion((current) => current + 1)}>
              <RefreshCw className="h-4 w-4" /> Retry
            </button>
          </div>
        ) : !svg ? (
          <div className="diagram-state" role="status">
            <LoaderCircle className="h-5 w-5 animate-spin" style={{ color: 'var(--accent)' }} />
            <div><strong>Rendering diagram</strong><p>Preparing the synchronized {artifact.title.toLowerCase()} view.</p></div>
          </div>
        ) : (
          <div className="diagram-scroll-region">
            <div className="diagram-canvas" dangerouslySetInnerHTML={{ __html: svg }} />
          </div>
        )}
      </div>

      <div className="mt-3 flex gap-2">
        <button
          type="button"
          onClick={() => setShowSource(showSource === 'hidden' ? 'mermaid' : 'hidden')}
          className="text-xs font-medium underline"
          style={{ color: 'var(--text-muted)' }}
        >
          {showSource === 'hidden' ? 'Show source' : 'Hide source'}
        </button>
      </div>

      {showSource !== 'hidden' ? (
        <pre className="mt-3 overflow-x-auto rounded-lg border p-3 text-xs" style={{ borderColor: 'var(--card-border)', background: 'var(--surface-strong)' }}>
          {showSource === 'mermaid' ? artifact.mermaid : artifact.plantuml}
        </pre>
      ) : null}
    </div>
  )
}
