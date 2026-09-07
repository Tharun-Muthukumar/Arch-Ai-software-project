import { X } from 'lucide-react'
import { useEffect, type ReactNode } from 'react'
import { createPortal } from 'react-dom'

interface ModalProps {
  open: boolean
  title: string
  description?: string
  children: ReactNode
  onClose: () => void
  width?: 'md' | 'lg'
}

export function Modal({ open, title, description, children, onClose, width = 'md' }: ModalProps) {
  useEffect(() => {
    if (!open) return
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [onClose, open])

  if (!open) return null
  return createPortal(
    <div className="modal-backdrop" role="presentation" onMouseDown={onClose}>
      <section
        className={`modal-panel ${width === 'lg' ? 'max-w-3xl' : 'max-w-xl'}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby="modal-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="flex items-start gap-4 border-b px-5 py-4" style={{ borderColor: 'var(--card-border)' }}>
          <div className="min-w-0 flex-1">
            <h2 id="modal-title" className="text-base font-semibold">{title}</h2>
            {description ? <p className="mt-1 text-sm leading-5 text-muted">{description}</p> : null}
          </div>
          <button type="button" className="icon-button" aria-label="Close dialog" title="Close" onClick={onClose}>
            <X className="h-4 w-4" />
          </button>
        </header>
        <div className="max-h-[72vh] overflow-y-auto p-5">{children}</div>
      </section>
    </div>,
    document.body,
  )
}
