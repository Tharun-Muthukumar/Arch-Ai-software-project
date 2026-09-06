import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowUpRight,
  Clock3,
  LoaderCircle,
  Search,
  Share2,
  Trash2,
  UserMinus,
  Users,
} from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import {
  deleteConversation,
  getConversation,
  listHistory,
  revokeConversationShare,
  searchUsers,
  shareConversation,
} from '../lib/api'
import { cn, formatUpdatedAt, getErrorMessage } from '../lib/utils'

type HistoryFilter = 'all' | 'owned' | 'shared'

export function HistoryPage() {
  const queryClient = useQueryClient()
  const [searchParams, setSearchParams] = useSearchParams()
  const [filter, setFilter] = useState<HistoryFilter>('all')
  const [recipientQuery, setRecipientQuery] = useState('')
  const selectedId = searchParams.get('conversation')

  const historyQuery = useQuery({ queryKey: ['history'], queryFn: listHistory })
  const detailQuery = useQuery({
    queryKey: ['history', selectedId],
    queryFn: () => getConversation(selectedId ?? ''),
    enabled: Boolean(selectedId),
  })
  const userSearchQuery = useQuery({
    queryKey: ['user-search', recipientQuery.trim()],
    queryFn: () => searchUsers(recipientQuery.trim()),
    enabled: recipientQuery.trim().length >= 2 && detailQuery.data?.permission === 'OWNER',
  })

  const filteredHistory = useMemo(() => {
    const items = historyQuery.data ?? []
    if (filter === 'owned') return items.filter((item) => item.permission === 'OWNER')
    if (filter === 'shared') return items.filter((item) => item.permission === 'VIEW')
    return items
  }, [filter, historyQuery.data])

  const shareMutation = useMutation({
    mutationFn: (recipientId: string) => {
      if (!selectedId) throw new Error('Select a conversation first.')
      return shareConversation(selectedId, recipientId)
    },
    onSuccess: async () => {
      setRecipientQuery('')
      await queryClient.invalidateQueries({ queryKey: ['history', selectedId] })
    },
  })
  const revokeMutation = useMutation({
    mutationFn: (recipientId: string) => {
      if (!selectedId) throw new Error('Select a conversation first.')
      return revokeConversationShare(selectedId, recipientId)
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['history', selectedId] }),
  })
  const deleteMutation = useMutation({
    mutationFn: () => {
      if (!selectedId) throw new Error('Select a conversation first.')
      return deleteConversation(selectedId)
    },
    onSuccess: async () => {
      setSearchParams({})
      await queryClient.invalidateQueries({ queryKey: ['history'] })
      await queryClient.invalidateQueries({ queryKey: ['workspaces'] })
    },
  })

  function selectConversation(conversationId: string) {
    setRecipientQuery('')
    setSearchParams({ conversation: conversationId })
  }

  function confirmDelete() {
    if (window.confirm('Delete this conversation and its generated workspace?')) {
      deleteMutation.mutate()
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <span className="pill">Saved automatically</span>
          <h2 className="section-title mt-2">History</h2>
        </div>
        <div className="inline-flex rounded-lg border p-1" style={{ borderColor: 'var(--card-border)' }}>
          {(['all', 'owned', 'shared'] as const).map((item) => (
            <button
              key={item}
              type="button"
              className={cn(
                'rounded-md px-3 py-1.5 text-sm capitalize transition',
                filter === item ? 'bg-amber-600 font-medium text-white' : 'text-slate-400 hover:text-white',
              )}
              onClick={() => setFilter(item)}
            >
              {item}
            </button>
          ))}
        </div>
      </div>

      {historyQuery.isError ? (
        <div className="panel text-sm text-red-300" role="alert">{getErrorMessage(historyQuery.error)}</div>
      ) : null}

      <div className="grid min-h-[560px] gap-4 lg:grid-cols-[340px_minmax(0,1fr)]">
        <aside className="panel p-0">
          <div className="border-b px-4 py-3" style={{ borderColor: 'var(--card-border)' }}>
            <span className="text-sm font-semibold">Conversations</span>
          </div>
          <div className="max-h-[680px] overflow-y-auto p-2">
            {historyQuery.isLoading ? (
              <div className="flex items-center gap-2 p-3 text-sm text-muted"><LoaderCircle className="h-4 w-4 animate-spin" /> Loading history...</div>
            ) : filteredHistory.length === 0 ? (
              <p className="p-3 text-sm text-muted">No conversations in this view.</p>
            ) : (
              filteredHistory.map((conversation) => (
                <button
                  key={conversation.id}
                  type="button"
                  onClick={() => selectConversation(conversation.id)}
                  className={cn(
                    'mb-1 w-full rounded-md border px-3 py-3 text-left transition',
                    selectedId === conversation.id
                      ? 'border-amber-500 bg-amber-500/10'
                      : 'border-transparent hover:bg-white/5',
                  )}
                >
                  <div className="flex items-start justify-between gap-2">
                    <span className="line-clamp-2 text-sm font-medium">{conversation.title}</span>
                    {conversation.permission === 'VIEW' ? <Users className="mt-0.5 h-3.5 w-3.5 shrink-0 text-cyan-400" aria-label="Shared" /> : null}
                  </div>
                  <p className="mt-1 line-clamp-2 text-xs text-muted">{conversation.preview}</p>
                  <p className="mt-2 flex items-center gap-1 text-xs text-muted"><Clock3 className="h-3 w-3" /> {formatUpdatedAt(conversation.updated_at)}</p>
                </button>
              ))
            )}
          </div>
        </aside>

        <section className="panel min-w-0">
          {!selectedId ? (
            <div className="flex h-full min-h-72 items-center justify-center text-center text-sm text-muted">
              Select a conversation to view its prompts and generated result.
            </div>
          ) : detailQuery.isLoading ? (
            <div className="flex items-center gap-2 text-sm text-muted"><LoaderCircle className="h-4 w-4 animate-spin" /> Loading conversation...</div>
          ) : detailQuery.isError ? (
            <p className="text-sm text-red-300" role="alert">{getErrorMessage(detailQuery.error)}</p>
          ) : detailQuery.data ? (
            <div className="space-y-5">
              <header className="flex flex-wrap items-start justify-between gap-3 border-b pb-4" style={{ borderColor: 'var(--card-border)' }}>
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="pill">{detailQuery.data.permission === 'OWNER' ? 'Owned' : 'Shared view'}</span>
                    <span className="text-xs text-muted">Owner: {detailQuery.data.owner.username}</span>
                  </div>
                  <h3 className="mt-2 break-words text-xl font-semibold">{detailQuery.data.title}</h3>
                  <p className="mt-1 text-sm text-muted">{detailQuery.data.workspace.requirements.domain}</p>
                </div>
                <div className="flex gap-2">
                  <Link className="button-brand gap-2" to={`/wizard?workspace=${detailQuery.data.workspace_id}`}>
                    Open results <ArrowUpRight className="h-4 w-4" />
                  </Link>
                  {detailQuery.data.permission === 'OWNER' ? (
                    <button
                      type="button"
                      className="button-secondary px-3 text-red-300"
                      onClick={confirmDelete}
                      disabled={deleteMutation.isPending}
                      title="Delete conversation"
                      aria-label="Delete conversation"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  ) : null}
                </div>
              </header>

              <div className="space-y-3">
                {detailQuery.data.messages.map((message) => (
                  <article
                    key={message.id}
                    className={cn(
                      'rounded-md border-l-2 px-4 py-3',
                      message.role === 'user' ? 'border-amber-500 bg-amber-500/5' : 'border-cyan-500 bg-cyan-500/5',
                    )}
                  >
                    <div className="flex items-center justify-between gap-3">
                      <span className="text-xs font-semibold uppercase text-muted">{message.role === 'user' ? 'You' : 'ArchAI'}</span>
                      <time className="text-xs text-muted">{formatUpdatedAt(message.created_at)}</time>
                    </div>
                    <p className="mt-2 whitespace-pre-wrap break-words text-sm leading-6">{message.content}</p>
                  </article>
                ))}
              </div>

              {detailQuery.data.permission === 'OWNER' ? (
                <div className="border-t pt-5" style={{ borderColor: 'var(--card-border)' }}>
                  <div className="flex items-center gap-2"><Share2 className="h-4 w-4 text-amber-400" /><h4 className="font-semibold">Share read-only access</h4></div>
                  <label className="relative mt-3 block max-w-lg">
                    <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" />
                    <input
                      className="input-shell pl-9"
                      value={recipientQuery}
                      onChange={(event) => setRecipientQuery(event.target.value)}
                      placeholder="Search username or email"
                    />
                  </label>
                  {shareMutation.isError ? <p className="mt-2 text-sm text-red-300">{getErrorMessage(shareMutation.error)}</p> : null}
                  {recipientQuery.trim().length >= 2 ? (
                    <div className="mt-2 max-w-lg divide-y rounded-md border" style={{ borderColor: 'var(--card-border)' }}>
                      {userSearchQuery.isLoading ? <p className="p-3 text-sm text-muted">Searching...</p> : null}
                      {userSearchQuery.data?.map((result) => (
                        <div key={result.id} className="flex items-center justify-between gap-3 px-3 py-2" style={{ borderColor: 'var(--card-border)' }}>
                          <div className="min-w-0"><p className="text-sm font-medium">{result.username}</p><p className="truncate text-xs text-muted">{result.email}</p></div>
                          <button className="button-secondary px-3 py-1.5 text-xs" type="button" onClick={() => shareMutation.mutate(result.id)} disabled={shareMutation.isPending}>Share</button>
                        </div>
                      ))}
                      {userSearchQuery.data?.length === 0 ? <p className="p-3 text-sm text-muted">No matching users.</p> : null}
                    </div>
                  ) : null}

                  {detailQuery.data.shares.length > 0 ? (
                    <div className="mt-5 space-y-2">
                      <p className="text-sm font-medium">People with access</p>
                      {detailQuery.data.shares.map((share) => (
                        <div key={share.recipient.id} className="flex max-w-lg items-center justify-between gap-3 border-b py-2" style={{ borderColor: 'var(--card-border)' }}>
                          <div className="min-w-0"><p className="text-sm">{share.recipient.username}</p><p className="truncate text-xs text-muted">{share.recipient.email} · View only</p></div>
                          <button
                            type="button"
                            className="p-2 text-slate-400 hover:text-red-300"
                            onClick={() => revokeMutation.mutate(share.recipient.id)}
                            disabled={revokeMutation.isPending}
                            title="Revoke access"
                            aria-label={`Revoke access for ${share.recipient.username}`}
                          >
                            <UserMinus className="h-4 w-4" />
                          </button>
                        </div>
                      ))}
                    </div>
                  ) : null}
                </div>
              ) : (
                <p className="border-t pt-4 text-sm text-muted" style={{ borderColor: 'var(--card-border)' }}>
                  This conversation is shared with view-only permission.
                </p>
              )}
            </div>
          ) : null}
        </section>
      </div>
    </div>
  )
}
