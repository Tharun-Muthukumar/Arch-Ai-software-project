def test_cors_allows_local_preview_origin(client):
    response = client.options(
        "/api/v1/workspaces",
        headers={
            "Origin": "http://127.0.0.1:4173",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:4173"


def test_cors_allows_dynamic_local_development_port(client):
    response = client.options(
        "/api/v1/workspaces",
        headers={
            "Origin": "http://127.0.0.1:5199",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5199"

