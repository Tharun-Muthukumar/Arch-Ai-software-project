def test_health_check(client):
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "ArchAI"
    assert body["ollama_enabled"] is False
    assert body["ollama_reachable"] is False
    assert body["ollama_model_available"] is False

