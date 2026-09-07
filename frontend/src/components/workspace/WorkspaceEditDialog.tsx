import { AlertTriangle, Check, ChevronLeft, LoaderCircle, Plus, Sparkles, Trash2 } from 'lucide-react'
import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { useWorkspaceEditing } from '../../hooks/useWorkspaceEditing'
import { getErrorMessage } from '../../lib/utils'
import type { Workspace, WorkspaceEditPreview, WorkspaceEditRequest } from '../../types/api'
import { Modal } from '../ui/Modal'

export interface EditField {
  key: string
  label: string
  type?: 'text' | 'textarea' | 'select' | 'checkbox' | 'tags' | 'number' | 'database-fields'
  placeholder?: string
  help?: string
  options?: Array<{ label: string; value: string }>
  required?: boolean
}

interface WorkspaceEditDialogProps {
  open: boolean
  workspace: Workspace
  title: string
  description?: string
  edit: WorkspaceEditRequest
  fields?: EditField[]
  allowAi?: boolean
  onClose: () => void
}

function initialFormValue(edit: WorkspaceEditRequest) {
  if (typeof edit.value === 'string') return { value: edit.value }
  return { ...(edit.value ?? {}) }
}

export function WorkspaceEditDialog({
  open,
  workspace,
  title,
  description,
  edit,
  fields = [],
  allowAi = false,
  onClose,
}: WorkspaceEditDialogProps) {
  const editing = useWorkspaceEditing(workspace)
  const [formValue, setFormValue] = useState<Record<string, unknown>>(() => initialFormValue(edit))
  const [useAi, setUseAi] = useState(false)
  const [preview, setPreview] = useState<WorkspaceEditPreview | null>(null)
  const [aiChoice, setAiChoice] = useState<'suggestion' | 'original' | null>(null)
  const editKey = useMemo(() => JSON.stringify(edit), [edit])

  useEffect(() => {
    if (!open) return
    setFormValue(initialFormValue(edit))
    setUseAi(false)
    setPreview(null)
    setAiChoice(null)
    editing.preview.reset()
    editing.apply.reset()
    // editKey deliberately resets the form when the selected artifact changes.
  }, [editKey, open])

  function buildEdit(withAi = useAi): WorkspaceEditRequest {
    const value = typeof edit.value === 'string'
      ? String(formValue.value ?? '')
      : edit.operation === 'delete'
        ? undefined
        : formValue
    return { ...edit, value, use_ai: withAi }
  }

  async function handleReview(event: FormEvent) {
    event.preventDefault()
    const result = await editing.preview.mutateAsync(buildEdit())
    setPreview(result)
    setAiChoice(result.suggestion ? null : 'original')
  }

  async function handleApply() {
    if (!preview) return
    const chosen = aiChoice === 'suggestion'
      ? preview.edit
      : buildEdit(false)
    await editing.apply.mutateAsync(chosen)
    onClose()
  }

  const isDelete = edit.operation === 'delete'
  const originalText = typeof buildEdit(false).value === 'string' ? String(buildEdit(false).value) : ''
  const suggestedText = preview?.suggestion?.suggested_text ?? ''
  const suggestionDiffers = Boolean(preview?.suggestion && suggestedText !== originalText)

  return (
    <Modal open={open} title={title} description={description} onClose={onClose} width="lg">
      {!preview ? (
        <form onSubmit={(event) => void handleReview(event)}>
          {isDelete ? (
            <div className="notice notice-danger">
              <AlertTriangle className="h-4 w-4 shrink-0" />
              <p>This removes the item from the canonical project model. Review its dependency impact before applying.</p>
            </div>
          ) : (
            <div className="space-y-4">
              {fields.map((field) => (
                <EditorField
                  key={field.key}
                  field={field}
                  value={formValue[field.key]}
                  onChange={(value) => setFormValue((current) => ({ ...current, [field.key]: value }))}
                />
              ))}
              {allowAi ? (
                <label className="ai-toggle">
                  <input type="checkbox" checked={useAi} onChange={(event) => setUseAi(event.target.checked)} />
                  <Sparkles className="h-4 w-4" />
                  <span>
                    <strong>Improve with local AI</strong>
                    <small>Qwen can clarify meaning; you approve its suggestion before anything is saved.</small>
                  </span>
                </label>
              ) : null}
            </div>
          )}

          {editing.preview.isError ? (
            <div className="notice notice-danger mt-4" role="alert">
              <AlertTriangle className="h-4 w-4 shrink-0" />
              <span>{getErrorMessage(editing.preview.error)}</span>
            </div>
          ) : null}

          <div className="mt-6 flex items-center justify-end gap-2">
            <button type="button" className="button-secondary" onClick={onClose}>Cancel</button>
            <button type="submit" className="button-brand gap-2" disabled={editing.preview.isPending}>
              {editing.preview.isPending ? <LoaderCircle className="h-4 w-4 animate-spin" /> : null}
              {editing.preview.isPending
                ? useAi ? 'Understanding change...' : 'Checking dependencies...'
                : 'Review impact'}
            </button>
          </div>
        </form>
      ) : (
        <div>
          {preview.suggestion ? (
            <section className="mb-5">
              <div className="flex items-center justify-between gap-3">
                <h3 className="eyebrow">AI suggestion</h3>
                <span className="status-chip status-info">
                  {preview.suggestion.source === 'ollama' ? 'Ollama / Qwen' : 'Safe fallback'}
                </span>
              </div>
              {suggestionDiffers ? (
                <div className="mt-3 grid gap-3 md:grid-cols-2">
                  <button type="button" className={`choice-panel ${aiChoice === 'original' ? 'is-selected' : ''}`} onClick={() => setAiChoice('original')}>
                    <span className="choice-label">Keep original</span>
                    <span>{originalText}</span>
                  </button>
                  <button type="button" className={`choice-panel ${aiChoice === 'suggestion' ? 'is-selected' : ''}`} onClick={() => setAiChoice('suggestion')}>
                    <span className="choice-label">Use suggestion</span>
                    <span>{suggestedText}</span>
                  </button>
                </div>
              ) : (
                <div className="notice notice-info mt-3">The validated suggestion preserves your original wording.</div>
              )}
              <p className="mt-3 text-sm leading-6 text-muted">{preview.suggestion.rationale}</p>
              {preview.suggestion.inferred_characteristics.length > 0 ? (
                <div className="mt-3">
                  <div className="eyebrow">Validated implications</div>
                  <ul className="mt-2 space-y-1 text-sm text-muted">
                    {preview.suggestion.inferred_characteristics.map((item) => <li key={item}>{item}</li>)}
                  </ul>
                </div>
              ) : null}
              {preview.suggestion.clarification_questions.length > 0 ? (
                <div className="notice notice-info mt-3">
                  <div>
                    <strong>Information still needed</strong>
                    {preview.suggestion.clarification_questions.map((item) => <p key={item} className="mt-1">{item}</p>)}
                  </div>
                </div>
              ) : null}
            </section>
          ) : null}

          <section>
            <h3 className="eyebrow">Change impact</h3>
            <div className="impact-grid mt-3">
              {preview.impact.items.map((item) => (
                <div key={item.area} className="impact-row">
                  <div className="flex items-center gap-2">
                    <span className={`impact-dot impact-${item.level}`} />
                    <strong className="text-sm">{item.area}</strong>
                  </div>
                  <span className={`status-chip status-${item.level}`}>{item.level}</span>
                  <p className="text-xs leading-5 text-muted">{item.summary}</p>
                </div>
              ))}
            </div>
          </section>

          {preview.warnings.map((warning) => (
            <div key={warning} className="notice notice-warning mt-3">{warning}</div>
          ))}
          {editing.apply.isError ? (
            <div className="notice notice-danger mt-3" role="alert">{getErrorMessage(editing.apply.error)}</div>
          ) : null}

          <div className="mt-6 flex flex-wrap items-center justify-between gap-2">
            <button type="button" className="button-secondary gap-2" onClick={() => setPreview(null)}>
              <ChevronLeft className="h-4 w-4" /> Edit
            </button>
            <button
              type="button"
              className={isDelete ? 'button-danger gap-2' : 'button-brand gap-2'}
              disabled={editing.apply.isPending || (suggestionDiffers && aiChoice === null)}
              onClick={() => void handleApply()}
            >
              {editing.apply.isPending ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
              {editing.apply.isPending ? 'Synchronizing workspace...' : isDelete ? 'Delete and update' : 'Apply change'}
            </button>
          </div>
        </div>
      )}
    </Modal>
  )
}

function EditorField({ field, value, onChange }: { field: EditField; value: unknown; onChange: (value: unknown) => void }) {
  const inputId = `edit-${field.key}`
  const label = <span className="field-label">{field.label}</span>
  if (field.type === 'checkbox') {
    return (
      <label className="toggle-row" htmlFor={inputId}>
        <span>{label}{field.help ? <small>{field.help}</small> : null}</span>
        <input id={inputId} type="checkbox" checked={value === true} onChange={(event) => onChange(event.target.checked)} />
      </label>
    )
  }
  if (field.type === 'number') {
    return (
      <label className="block" htmlFor={inputId}>
        {label}
        <input id={inputId} type="number" min={1} className="input-shell mt-1.5" value={value === null || value === undefined ? '' : Number(value)} onChange={(event) => onChange(event.target.value ? Number(event.target.value) : null)} placeholder={field.placeholder} required={field.required} />
        {field.help ? <span className="field-help">{field.help}</span> : null}
      </label>
    )
  }
  if (field.type === 'database-fields') {
    const databaseFields = Array.isArray(value) ? value as Array<Record<string, unknown>> : []
    const updateField = (index: number, key: string, nextValue: unknown) => {
      onChange(databaseFields.map((item, itemIndex) => itemIndex === index ? { ...item, [key]: nextValue } : item))
    }
    return (
      <fieldset>
        <div className="flex items-center justify-between gap-3">
          <legend className="field-label">{field.label}</legend>
          <button type="button" className="button-secondary gap-2 px-3 py-2" onClick={() => onChange([...databaseFields, { name: '', data_type: 'text', nullable: false, indexed: false, description: '' }])}><Plus className="h-3.5 w-3.5" />Add field</button>
        </div>
        <div className="mt-3 space-y-3">
          {databaseFields.map((item, index) => (
            <div key={index} className="field-editor-row">
              <input className="input-shell" aria-label={`Field ${index + 1} name`} value={String(item.name ?? '')} onChange={(event) => updateField(index, 'name', event.target.value)} placeholder="field_name" required />
              <input className="input-shell" aria-label={`Field ${index + 1} data type`} value={String(item.data_type ?? '')} onChange={(event) => updateField(index, 'data_type', event.target.value)} placeholder="data type" required />
              <input className="input-shell md:col-span-2" aria-label={`Field ${index + 1} description`} value={String(item.description ?? '')} onChange={(event) => updateField(index, 'description', event.target.value)} placeholder="Purpose of this field" required />
              <label className="check-label"><input type="checkbox" checked={item.nullable === true} onChange={(event) => updateField(index, 'nullable', event.target.checked)} />Nullable</label>
              <label className="check-label"><input type="checkbox" checked={item.indexed === true} onChange={(event) => updateField(index, 'indexed', event.target.checked)} />Indexed</label>
              <button type="button" className="icon-button danger-hover ml-auto" title="Remove field" aria-label={`Remove field ${index + 1}`} onClick={() => onChange(databaseFields.filter((_, itemIndex) => itemIndex !== index))}><Trash2 className="h-3.5 w-3.5" /></button>
            </div>
          ))}
          {databaseFields.length === 0 ? <div className="empty-row">No fields. Add at least the attributes this entity needs.</div> : null}
        </div>
      </fieldset>
    )
  }
  if (field.type === 'select') {
    return (
      <label className="block" htmlFor={inputId}>
        {label}
        <select id={inputId} className="input-shell mt-1.5" value={String(value ?? '')} onChange={(event) => onChange(event.target.value)} required={field.required}>
          {field.options?.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
        </select>
        {field.help ? <span className="field-help">{field.help}</span> : null}
      </label>
    )
  }
  if (field.type === 'textarea') {
    return (
      <label className="block" htmlFor={inputId}>
        {label}
        <textarea id={inputId} className="input-shell mt-1.5 min-h-28 resize-y" value={String(value ?? '')} onChange={(event) => onChange(event.target.value)} placeholder={field.placeholder} required={field.required} />
        {field.help ? <span className="field-help">{field.help}</span> : null}
      </label>
    )
  }
  if (field.type === 'tags') {
    const display = Array.isArray(value) ? value.join(', ') : String(value ?? '')
    return (
      <label className="block" htmlFor={inputId}>
        {label}
        <input id={inputId} className="input-shell mt-1.5" value={display} onChange={(event) => onChange(event.target.value.split(',').map((item) => item.trim()).filter(Boolean))} placeholder={field.placeholder} required={field.required} />
        <span className="field-help">{field.help ?? 'Separate multiple values with commas.'}</span>
      </label>
    )
  }
  return (
    <label className="block" htmlFor={inputId}>
      {label}
      <input id={inputId} className="input-shell mt-1.5" value={String(value ?? '')} onChange={(event) => onChange(event.target.value)} placeholder={field.placeholder} required={field.required} />
      {field.help ? <span className="field-help">{field.help}</span> : null}
    </label>
  )
}
