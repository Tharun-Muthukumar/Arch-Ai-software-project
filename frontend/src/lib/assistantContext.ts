import type { AssistantSelection } from '../types/api'

export function openAssistantWithSelection(selection: AssistantSelection) {
  window.dispatchEvent(new CustomEvent('archai:assistant-selection', { detail: selection }))
  window.dispatchEvent(new CustomEvent('archai:assistant-open'))
}

