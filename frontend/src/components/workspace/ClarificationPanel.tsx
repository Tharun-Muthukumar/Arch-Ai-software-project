import { LoaderCircle, Send } from 'lucide-react'
import { useEffect, useState, type FormEvent } from 'react'
import type { Workspace } from '../../types/api'

interface ClarificationPanelProps {
  workspace: Workspace
  isPending: boolean
  onSubmit: (answers: Record<string, string>) => void
}

export function ClarificationPanel({
  workspace,
  isPending,
  onSubmit,
}: ClarificationPanelProps) {
  const [answers, setAnswers] = useState<Record<string, string>>({})

  useEffect(() => {
    setAnswers({})
  }, [workspace.id])

  if (!workspace.clarification_plan.questions.length) {
    return (
      <div className="flex items-center justify-between gap-3 rounded-lg border px-4 py-2.5 text-xs" style={{ borderColor: 'var(--card-border)', background: 'var(--surface)' }}>
        <div className="flex items-center gap-2.5">
          <span className="pill">Phase 2</span>
          <span className="font-medium" style={{ color: 'var(--text)' }}>Clarifications complete</span>
          <span className="hidden sm:inline" style={{ color: 'var(--text-muted)' }}>— all architectural questions resolved.</span>
        </div>
        <span className="font-mono text-[11px]" style={{ color: 'var(--success)' }}>100% complete</span>
      </div>
    )
  }

  function updateAnswer(key: string, value: string) {
    setAnswers((currentAnswers) => ({ ...currentAnswers, [key]: value }))
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const completedAnswers = Object.fromEntries(
      Object.entries(answers).filter(([, value]) => value.trim().length > 0),
    )
    if (Object.keys(completedAnswers).length > 0) {
      onSubmit(completedAnswers)
    }
  }

  const hasAnswers = Object.values(answers).some((value) => value.trim().length > 0)

  return (
    <form className="panel" onSubmit={handleSubmit}>
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <span className="pill">Phase 2</span>
          <h3 className="mt-2 text-lg font-semibold">Follow-up questions</h3>
          <p className="mt-1 text-sm" style={{ color: 'var(--text-muted)' }}>
            Just the essentials — answer what you know, skip the rest. Anything unanswered gets a safe default.
          </p>
        </div>
        <span className="text-sm font-medium">
          {workspace.clarification_plan.completeness_score}% complete
        </span>
      </div>

      <div className="mt-4 space-y-3">
        {workspace.clarification_plan.questions.map((question) => (
          <div
            key={question.key}
            className="rounded-lg border p-3"
            style={{ borderColor: 'var(--card-border)' }}
          >
            <div className="flex items-center gap-2">
              <span className="pill">{question.priority}</span>
              <span className="text-xs" style={{ color: 'var(--text-muted)' }}>
                {question.category}
              </span>
            </div>
            <p className="mt-2 font-medium text-sm">{question.question}</p>
            {question.options.length > 0 ? (
              <select
                aria-label={question.question}
                className="input-shell mt-2"
                value={answers[question.key] ?? ''}
                onChange={(event) => updateAnswer(question.key, event.target.value)}
              >
                <option value="">Select an answer</option>
                {question.options.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </select>
            ) : (
              <textarea
                aria-label={question.question}
                className="input-shell mt-2 resize-y"
                rows={2}
                value={answers[question.key] ?? ''}
                onChange={(event) => updateAnswer(question.key, event.target.value)}
                placeholder="Type an answer, or enter 'unknown'"
              />
            )}
          </div>
        ))}
      </div>

      <div className="mt-4 flex justify-end">
        <button
          type="submit"
          disabled={isPending || !hasAnswers}
          className="button-brand gap-2 text-sm"
        >
          {isPending ? (
            <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden="true" />
          ) : (
            <Send className="h-4 w-4" aria-hidden="true" />
          )}
          {isPending ? 'Refreshing results...' : 'Apply answers'}
        </button>
      </div>
    </form>
  )
}
