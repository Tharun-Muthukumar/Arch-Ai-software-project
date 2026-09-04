from app.services.requirement_analyzer import RequirementAnalyzer


def test_workspace_pipeline_and_change_request(client, monkeypatch):
    create_response = client.post(
        "/api/v1/workspaces",
        json={
            "title": "PharmaScale",
            "description": "Build an online pharmacy for 500,000 users with prescription verification and secure checkout.",
            "business_context": "The platform needs rapid go-live and clear compliance controls.",
            "budget": "medium",
            "preferred_cloud": "AWS",
        },
    )

    assert create_response.status_code == 201
    workspace = create_response.json()
    assert len(workspace["architectures"]) == 3
    assert workspace["recommendation"]["recommended_architecture_name"]
    assert "## Recommendation" in workspace["documentation_markdown"]

    def fail_if_reanalyzed(*args, **kwargs):
        raise AssertionError("Clarification updates must not rerun requirement extraction")

    monkeypatch.setattr(RequirementAnalyzer, "analyze", fail_if_reanalyzed)

    clarification_response = client.post(
        f"/api/v1/workspaces/{workspace['id']}/clarifications",
        json={"answers": {"auth": "SSO/SAML", "scale": "250k+ users", "sla": "99.9%"}},
    )
    assert clarification_response.status_code == 200
    clarified = clarification_response.json()
    assert clarified["answers"]["auth"] == "SSO/SAML"
    assert "Use SSO/SAML for user authentication." in clarified["requirements"]["functional_requirements"]

    change_response = client.post(
        f"/api/v1/workspaces/{workspace['id']}/changes",
        json={"change_request": "Add notifications and analytics exports for operational teams."},
    )
    assert change_response.status_code == 200
    changed = change_response.json()
    assert changed["impact_history"][-1]["impacted_modules"]
    assert any(
        "notification" in requirement.lower()
        for requirement in changed["requirements"]["functional_requirements"]
    )

    markdown_response = client.get(
        f"/api/v1/workspaces/{workspace['id']}/documentation/markdown"
    )
    assert markdown_response.status_code == 200
    assert markdown_response.text.startswith("# PharmaScale")

    pdf_response = client.get(f"/api/v1/workspaces/{workspace['id']}/documentation/pdf")
    assert pdf_response.status_code == 200
    assert pdf_response.headers["content-type"] == "application/pdf"
