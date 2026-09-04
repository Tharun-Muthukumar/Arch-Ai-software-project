from app.services.requirement_analyzer import RequirementAnalyzer


def _model_output() -> dict:
    return {
        "domain": "Model-Inferred Specialized Domain",
        "summary": "A specialized system that processes source records and reviewed transitions.",
        "functional_requirements": [
            "Process the source records named in the brief.",
            "Allow the named reviewer to approve transitions.",
            "Use Kafka for all transitions at 99.9% availability.",
        ],
        "non_functional_requirements": [
            "Preserve source record integrity while transitions are reviewed.",
            "Keep review decisions traceable to the named reviewer.",
            "Support offline review access.",
            "Provide realtime transition updates.",
            "Ensure compatibility with external archive systems.",
        ],
        "actors": ["Named Reviewer", "System"],
        "domain_entities": ["Source Record", "Reviewed Transition"],
        "domain_workflows": ["Process Source Record", "Approve Transition"],
        "integrations": [],
        "data_characteristics": [],
        "explicit_constraints": [],
        "assumptions": [],
        "open_questions": [
            "What workload volume should the system support?",
            "Should this use a multi-region deployment?",
        ],
    }


def test_unknown_domain_sends_raw_requirement_before_fallback(monkeypatch):
    analyzer = RequirementAnalyzer()
    captured: dict = {}

    def fake_generate(stage, input_data, **kwargs):
        captured.update(
            {"stage": stage, "input_data": input_data, "options": kwargs}
        )
        return _model_output()

    monkeypatch.setattr(analyzer.ai_client, "generate", fake_generate)
    result = analyzer.analyze(
        title="Opaque Process",
        description="Process source records and let the named reviewer approve transitions.",
        constraints=["Must preserve the supplied source record."],
    )

    assert captured["stage"] == "unknown-domain-requirement-extraction"
    assert captured["input_data"]["raw_requirement"]["description"].startswith(
        "Process source records"
    )
    assert captured["options"]["response_schema"]
    assert result.analysis_source == "ollama-pretrained"
    assert result.domain == "Model-Inferred Specialized Domain"
    assert result.scale_profile == "unknown"
    assert result.constraints == ["Must preserve the supplied source record."]
    assert not any("Kafka" in item for item in result.functional_requirements)
    assert not any("99.9" in item for item in result.functional_requirements)
    assert not any("offline" in item.lower() for item in result.non_functional_requirements)
    assert not any("realtime" in item.lower() for item in result.non_functional_requirements)
    assert not any("external archive" in item.lower() for item in result.non_functional_requirements)
    assert not any("multi-region" in item.lower() for item in result.open_questions)
    assert [actor.name for actor in result.actors] == ["Named Reviewer"]
    assert result.analysis_warnings


def test_unknown_domain_uses_honest_fallback_when_ollama_fails(monkeypatch):
    analyzer = RequirementAnalyzer()
    monkeypatch.setattr(analyzer.ai_client, "generate", lambda *args, **kwargs: None)

    result = analyzer.analyze(
        title="Opaque Process",
        description="Retain the raw request exactly enough for a later clarification.",
    )

    assert result.analysis_source == "conservative-fallback"
    assert result.domain == "Unknown domain"
    assert result.scale_profile == "unknown"
    assert result.functional_requirements == [
        "Retain the raw request exactly enough for a later clarification."
    ]
    assert result.open_questions


def test_uncovered_prose_is_not_appended_as_a_duplicate_functional_requirement():
    analyzer = RequirementAnalyzer()

    functional, constraints, integrations = analyzer._preserve_uncovered_clauses(
        ["Process source records.", "Allow the named reviewer to approve transitions."],
        [],
        [],
        "allows ye reviewer to process records and aprove transitions",
        None,
    )

    assert len(functional) == 2
    assert constraints == []
    assert integrations == []


def test_clarification_answers_update_existing_requirements_without_reanalysis():
    analyzer = RequirementAnalyzer()
    requirements = analyzer._conservative_fallback(
        "Opaque Process",
        "Process source records.",
        [],
    )

    updated = analyzer.apply_clarifications(
        requirements,
        {
            "auth": "SSO/SAML",
            "scale": "Pilot workload",
            "preferred_cloud": "No preference",
            "domain_open_1": "Reviewers may approve or reject a record.",
        },
        {"domain_open_1": "Which outcomes may a reviewer select?"},
    )

    assert "Use SSO/SAML for user authentication." in updated.functional_requirements
    assert updated.scale_profile == "startup-scale"
    assert any(
        "Reviewers may approve or reject a record" in item
        for item in updated.constraints
    )
    assert not any("hosting preference" in item for item in updated.constraints)
