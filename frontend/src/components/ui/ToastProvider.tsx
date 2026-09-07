import { AlertCircle, CheckCircle2, Info, X } from 'lucide-react'
import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'

type ToastTone = 'success' | 'danger' | 'info'

interface ToastInput {
  title: string
  description?: string
  tone?: ToastTone
}

interface ToastItem extends ToastInput {
  id: number
}

const ToastContext = createContext<{ showToast: (toast: ToastInput) => void } | null>(null)

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([])
  const showToast = useCallback((toast: ToastInput) => {
    const id = Date.now() + Math.floor(Math.random() * 1000)
    setToasts((current) => [...current.slice(-2), { ...toast, id }])
    window.setTimeout(() => {
      setToasts((current) => current.filter((item) => item.id !== id))
    }, 5000)
  }, [])
  const value = useMemo(() => ({ showToast }), [showToast])

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="pointer-events-none fixed bottom-4 right-4 z-[80] flex w-[min(390px,calc(100vw-2rem))] flex-col gap-2" aria-live="polite">
        {toasts.map((toast) => {
          const Icon = toast.tone === 'danger' ? AlertCircle : toast.tone === 'info' ? Info : CheckCircle2
          return (
            <div key={toast.id} className={`toast pointer-events-auto toast-${toast.tone ?? 'success'}`} role="status">
              <Icon className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
              <div className="min-w-0 flex-1">
                <div className="text-sm font-semibold">{toast.title}</div>
                {toast.description ? <div className="mt-0.5 text-xs leading-5 text-muted">{toast.description}</div> : null}
              </div>
              <button
                type="button"
                className="icon-button h-7 w-7"
                aria-label="Dismiss notification"
                onClick={() => setToasts((current) => current.filter((item) => item.id !== toast.id))}
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
          )
        })}
      </div>
    </ToastContext.Provider>
  )
}

export function useToast() {
  const context = useContext(ToastContext)
  if (!context) throw new Error('useToast must be used inside ToastProvider')
  return context
}
