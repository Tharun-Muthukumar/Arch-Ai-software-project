export interface HealthStatus {
  status: string
  service: string
  environment: string
  ollama_enabled: boolean
  ollama_reachable: boolean
  ollama_model: string
  ollama_model_available: boolean
}

