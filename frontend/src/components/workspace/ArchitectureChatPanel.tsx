import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import {
  AlertTriangle,
  Check,
  ImagePlus,
  LoaderCircle,
  Send,
  Sparkles,
  X,
  XCircle,
} from 'lucide-react'
import { applyArchitectureChatProposal, sendArchitectureChat } from '../../lib/api'
import { syncWorkspaceResult, WORKSPACE_WRITE_KEY } from '../../lib/workspaceSync'
import { getErrorMessage } from '../../lib/utils'
import type {
  ArchitectureChangeProposal,
  ArchitectureChatHistoryMessage,
  ArchitectureChatImage,
  ArchitectureChatResponse,
  ArchitecturePatchOperation,
  Workspace,
} from '../../types/api'
import { useToast } from '../ui/ToastProvider'

interface ChatEntry {
  id: string
  role: 'user' | 'assistant'
  content: string
  response?: ArchitectureChatResponse
  proposalStatus?: 'pending' | 'applied' | 'rejected'
}

interface ArchitectureChatPanelProps {
  workspace: Workspace
  architectureId: string
  open: boolean
  initialMessage?: string | null
  onClose: () => void
}

interface PendingMessage {
  content: string
  images: ArchitectureChatImage[]
}

function storageKey(workspaceId: string) {
  return `archai-architecture-chat:${workspaceId}`
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isStoredResponse(value: unknown) {
  if (!isRecord(value) ||
      (value.type !== 'question' && value.type !== 'architecture_change') ||
      typeof value.answer !== 'string' ||
      !Array.isArray(value.affected_components) ||
      !Array.isArray(value.recommendations)) return false
  if (value.type === 'question') return value.proposal == null
  const proposal = value.proposal
  return isRecord(proposal) &&
    typeof proposal.proposal_id === 'string' &&
    typeof proposal.architecture_id === 'string' &&
    typeof proposal.base_updated_at === 'string' &&
    typeof proposal.summary === 'string' &&
    typeof proposal.reasoning === 'string' &&
    typeof proposal.risk_level === 'string' &&
    typeof proposal.auto_apply_safe === 'boolean' &&
    Array.isArray(proposal.architecture_changes) &&
    Array.isArray(proposal.requirement_additions) &&
    Array.isArray(proposal.affected_components) &&
    Array.isArray(proposal.tradeoffs)
}

function loadEntries(workspaceId: string): ChatEntry[] {
  try {
    const raw = window.sessionStorage.getItem(storageKey(workspaceId))
    if (!raw) return []
    const parsed = JSON.parse(raw) as unknown
    if (!Array.isArray(parsed)) return []
    return parsed.filter((item): item is ChatEntry => {
      if (!isRecord(item)) return false
      const candidate = item as Partial<ChatEntry>
      const basicEntry = (
        typeof candidate.id === 'string' &&
        (candidate.role === 'user' || candidate.role === 'assistant') &&
        typeof candidate.content === 'string'
      )
      const validStatus = candidate.proposalStatus === undefined ||
        ['pending', 'applied', 'rejected'].includes(candidate.proposalStatus)
      return basicEntry && validStatus &&
        (candidate.response === undefined || isStoredResponse(candidate.response))
    })
  } catch {
    return []
  }
}

function operationLabel(operation: ArchitecturePatchOperation) {
  if (operation.operation === 'add_component') {
    return `Add ${operation.component?.name ?? 'component'}`
  }
  if (operation.operation === 'update_component') {
    return `Update ${operation.component_name ?? 'component'}`
  }
  if (operation.operation === 'remove_component') {
    return `Remove ${operation.component_name ?? 'component'}`
  }
  if (operation.operation === 'replace_text') {
    return `Replace ${operation.from_value ?? 'value'} with ${operation.to_value ?? 'new value'}`
  }
  return `Update ${(operation.field ?? 'architecture field').replaceAll('_', ' ')}`
}

function proposalIsStale(proposal: ArchitectureChangeProposal, workspace: Workspace) {
  return new Date(proposal.base_updated_at).getTime() !== new Date(workspace.updated_at).getTime()
}

export function ArchitectureChatPanel({
  workspace,
  architectureId,
  open,
  initialMessage,
  onClose,
}: ArchitectureChatPanelProps) {
  const queryClient = useQueryClient()
  const { showToast } = useToast()
  const [entries, setEntries] = useState<ChatEntry[]>(() => loadEntries(workspace.id))
  const [message, setMessage] = useState('')
  const [attachment, setAttachment] = useState<ArchitectureChatImage | null>(null)
  const [error, setError] = useState<string | null>(null)
  const seededMessage = useRef<string | null>(null)
  const autoApplyAttempted = useRef<string | null>(null)
  const endRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    setEntries(loadEntries(workspace.id))
    setAttachment(null)
    setError(null)
    seededMessage.current = null
  }, [workspace.id])

  useEffect(() => {
    window.sessionStorage.setItem(storageKey(workspace.id), JSON.stringify(entries.slice(-30)))
    endRef.current?.scrollIntoView?.({ behavior: 'smooth', block: 'nearest' })
  }, [entries, workspace.id])

  useEffect(() => {
    if (!open || !initialMessage || seededMessage.current === initialMessage) return
    setMessage(initialMessage)
    seededMessage.current = initialMessage
  }, [initialMessage, open])

  useEffect(() => {
    if (!open) return
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [onClose, open])

  const history = useMemo<ArchitectureChatHistoryMessage[]>(
    () => entries.slice(-8).map((entry) => ({ role: entry.role, content: entry.content })),
    [entries],
  )

  const applyMutation = useMutation({
    mutationKey: [...WORKSPACE_WRITE_KEY, 'architecture-chat'],
    mutationFn: (proposal: ArchitectureChangeProposal) =>
      applyArchitectureChatProposal(workspace.id, proposal),
    onSuccess: (result, proposal) => {
      syncWorkspaceResult(queryClient, result.workspace)
      setEntries((current) => current.map((entry) =>
        entry.response?.proposal?.proposal_id === proposal.proposal_id
          ? { ...entry, proposalStatus: 'applied' }
          : entry,
      ))
      showToast({
        title: 'Project updated',
        description: 'Dependent diagrams, scoring, documentation, and causal links were synchronized.',
      })
    },
    onError: (applyError) => {
      setError(getErrorMessage(applyError, 'The proposed change could not be applied.'))
    },
  })

  const sendMutation = useMutation({
    mutationFn: ({ content, images }: PendingMessage) => sendArchitectureChat(workspace.id, {
      message: content,
      architecture_id: architectureId,
      history,
      images,
    }),
    onSuccess: (response) => {
      setEntries((current) => [
        ...current,
        {
          id: crypto.randomUUID(),
          role: 'assistant',
          content: response.answer,
          response,
          proposalStatus: response.proposal ? 'pending' : undefined,
        },
      ])
    },
    onError: (requestError) => {
      setError(getErrorMessage(requestError, "AI Assistant couldn't process that request. Please try again."))
    },
  })

  useEffect(() => {
    const proposal = [...entries].reverse().find(
      (entry) => entry.proposalStatus === 'pending' && entry.response?.proposal?.auto_apply_safe,
    )?.response?.proposal
    if (!proposal || applyMutation.isPending || autoApplyAttempted.current === proposal.proposal_id) return
    autoApplyAttempted.current = proposal.proposal_id
    applyMutation.mutate(proposal)
  }, [applyMutation, entries])

  function submitMessage() {
    const content = message.trim() || 'Analyze the attached image and explain the relevant project or architecture implications.'
    if ((!message.trim() && !attachment) || sendMutation.isPending || applyMutation.isPending) return
    setError(null)
    setEntries((current) => [
      ...current,
      { id: crypto.randomUUID(), role: 'user', content },
    ])
    setMessage('')
    const images = attachment ? [attachment] : []
    setAttachment(null)
    sendMutation.mutate({ content, images })
  }

  function attachImage(file: File | undefined) {
    if (!file) return
    if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) {
      setError('Choose a PNG, JPEG, or WebP image.')
      return
    }
    if (file.size > 4 * 1024 * 1024) {
      setError('Images must be 4 MB or smaller.')
      return
    }
    const reader = new FileReader()
    reader.onload = () => {
      const result = typeof reader.result === 'string' ? reader.result : ''
      const data = result.split(',', 2)[1]
      if (!data) {
        setError('The image could not be read.')
        return
      }
      setAttachment({
        name: file.name,
        media_type: file.type as ArchitectureChatImage['media_type'],
        data,
      })
      setError(null)
    }
    reader.onerror = () => setError('The image could not be read.')
    reader.readAsDataURL(file)
  }

  function rejectProposal(proposalId: string) {
    setEntries((current) => current.map((entry) =>
      entry.response?.proposal?.proposal_id === proposalId
        ? { ...entry, proposalStatus: 'rejected' }
        : entry,
    ))
  }

  if (!open) return null

  return (
    <div className="architecture-chat-layer" role="presentation">
      <aside className="architecture-chat-panel" aria-label="AI Assistant panel">
        <header className="architecture-chat-header">
          <div className="brand-mark"><Sparkles className="h-4 w-4" /></div>
          <div className="min-w-0 flex-1">
            <h2 className="text-sm font-semibold">AI Assistant</h2>
            <p className="text-xs text-muted">Reason about or update any part of this project.</p>
          </div>
          <button type="button" className="icon-button" aria-label="Minimize AI Assistant" onClick={onClose}>
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="architecture-chat-messages" aria-live="polite">
          {entries.length === 0 ? (
            <div className="space-y-4 py-8">
              <div>
                <h3 className="text-base font-semibold">Work with your project</h3>
                <p className="mt-1 text-sm text-muted">Ask for reasoning, add project requirements, or refine the architecture.</p>
              </div>
              <div className="grid grid-cols-2 gap-2">
                {['Explain this design', 'Add a functional requirement', 'Add a constraint', 'Improve security'].map((prompt) => (
                  <button key={prompt} type="button" className="chat-prompt" onClick={() => setMessage(prompt)}>
                    {prompt}
                  </button>
                ))}
              </div>
            </div>
          ) : null}

          {entries.map((entry) => {
            const proposal = entry.response?.proposal
            const stale = proposal ? proposalIsStale(proposal, workspace) : false
            return (
              <div key={entry.id} className={entry.role === 'user' ? 'chat-row-user' : 'chat-row-assistant'}>
                <div className="chat-bubble">
                  <p className="whitespace-pre-wrap text-sm leading-6">{entry.content}</p>
                  {entry.response?.recommendations.length ? (
                    <ul className="mt-3 space-y-1 border-t pt-3 text-xs text-muted" style={{ borderColor: 'var(--card-border)' }}>
                      {entry.response.recommendations.map((item) => <li key={item}>{item}</li>)}
                    </ul>
                  ) : null}
                </div>

                {proposal ? (
                  <section className="change-proposal" aria-label="Proposed project change">
                    <div className="flex items-center justify-between gap-2">
                      <span className="eyebrow">Proposed change</span>
                      <span className={`risk-badge risk-${proposal.risk_level}`}>{proposal.risk_level} risk</span>
                    </div>
                    <h3 className="mt-2 text-sm font-semibold">{proposal.summary}</h3>
                    <p className="mt-1 text-xs leading-5 text-muted">{proposal.reasoning}</p>
                    <div className="mt-3 space-y-1.5">
                      {proposal.architecture_changes.map((operation, index) => (
                        <div key={`${operation.operation}-${index}`} className="proposal-line">
                          <Check className="h-3.5 w-3.5 shrink-0" />
                          <span>{operationLabel(operation)}</span>
                        </div>
                      ))}
                      {proposal.requirement_additions.map((addition) => (
                        <div key={`${addition.target_type}-${addition.text}`} className="proposal-line">
                          <Check className="h-3.5 w-3.5 shrink-0" />
                          <span>Add {addition.target_type.replaceAll('_', ' ')}: {addition.text}</span>
                        </div>
                      ))}
                    </div>
                    {proposal.affected_components.length ? (
                      <div className="mt-3">
                        <div className="text-[11px] font-semibold uppercase text-muted">Affected components</div>
                        <div className="mt-1 flex flex-wrap gap-1">
                          {proposal.affected_components.map((component) => <span key={component} className="tag-chip">{component}</span>)}
                        </div>
                      </div>
                    ) : null}
                    {proposal.tradeoffs.length ? (
                      <div className="mt-3 text-xs">
                        <div className="font-semibold">Trade-offs</div>
                        <ul className="mt-1 space-y-1 text-muted">
                          {proposal.tradeoffs.map((item) => <li key={item}>{item}</li>)}
                        </ul>
                      </div>
                    ) : null}
                    {stale && entry.proposalStatus === 'pending' ? (
                      <div className="mt-3 flex gap-2 rounded border border-amber-500/30 bg-amber-500/10 p-2 text-xs text-amber-200">
                        <AlertTriangle className="h-4 w-4 shrink-0" />
                        The architecture changed since this proposal was generated. Request a fresh proposal.
                      </div>
                    ) : null}
                    <div className="mt-4 flex items-center justify-end gap-2">
                      {entry.proposalStatus === 'pending' ? (
                        <>
                          <button type="button" className="button-secondary" onClick={() => rejectProposal(proposal.proposal_id)} disabled={applyMutation.isPending}>
                            Reject
                          </button>
                          <button type="button" className="button-brand" onClick={() => applyMutation.mutate(proposal)} disabled={stale || applyMutation.isPending}>
                            {applyMutation.isPending ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
                            Apply Changes
                          </button>
                        </>
                      ) : (
                        <span className={`proposal-status ${entry.proposalStatus === 'applied' ? 'is-applied' : ''}`}>
                          {entry.proposalStatus === 'applied' ? <Check className="h-3.5 w-3.5" /> : <XCircle className="h-3.5 w-3.5" />}
                          {entry.proposalStatus === 'applied' ? 'Applied' : 'Rejected'}
                        </span>
                      )}
                    </div>
                  </section>
                ) : null}
              </div>
            )
          })}
          {sendMutation.isPending ? (
            <div className="chat-row-assistant">
              <div className="chat-bubble flex items-center gap-2 text-sm text-muted" role="status">
                <LoaderCircle className="h-4 w-4 animate-spin" />
                {sendMutation.variables?.images.length ? 'Analyzing the image with the vision model...' : 'Reasoning with the current project context...'}
              </div>
            </div>
          ) : null}
          <div ref={endRef} />
        </div>

        <div className="architecture-chat-composer">
          {error ? <div className="mb-2 text-xs text-red-300" role="alert">{error}</div> : null}
          {attachment ? (
            <div className="assistant-attachment">
              <ImagePlus className="h-4 w-4" />
              <span>{attachment.name}</span>
              <button type="button" aria-label="Remove attached image" onClick={() => setAttachment(null)}><X className="h-3.5 w-3.5" /></button>
            </div>
          ) : null}
          <label htmlFor="architecture-chat-message" className="sr-only">Message AI Assistant</label>
          <div className="flex items-end gap-2">
            <textarea
              id="architecture-chat-message"
              className="input-shell min-h-[80px] resize-none"
              value={message}
              maxLength={3000}
              placeholder="Ask, reason, or change requirements, constraints, and architecture..."
              onChange={(event) => setMessage(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && !event.shiftKey) {
                  event.preventDefault()
                  submitMessage()
                }
              }}
            />
            <label className="icon-button h-10 w-10 shrink-0 cursor-pointer" title="Attach image" aria-label="Attach image">
              <ImagePlus className="h-4 w-4" />
              <input
                type="file"
                className="sr-only"
                accept="image/png,image/jpeg,image/webp"
                disabled={sendMutation.isPending || applyMutation.isPending}
                onChange={(event) => {
                  attachImage(event.target.files?.[0])
                  event.currentTarget.value = ''
                }}
              />
            </label>
            <button type="button" className="button-brand h-10 w-10 shrink-0 px-0" aria-label="Send message" disabled={(!message.trim() && !attachment) || sendMutation.isPending || applyMutation.isPending} onClick={submitMessage}>
              <Send className="h-4 w-4" />
            </button>
          </div>
          <div className="mt-1 text-right text-[10px] text-muted">{message.length}/3000</div>
        </div>
      </aside>
    </div>
  )
}
