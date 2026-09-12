export interface HealthStatus {
  status: string
  service: string
  environment: string
  ollama_enabled: boolean
  ollama_reachable: boolean
  ollama_model: string
  ollama_model_available: boolean
  ollama_assistant_model?: string
  ollama_assistant_model_available?: boolean
  ollama_vision_model?: string
  ollama_vision_model_available?: boolean
}

