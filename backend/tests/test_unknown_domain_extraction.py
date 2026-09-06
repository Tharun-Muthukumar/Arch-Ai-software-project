import re

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


def test_explicit_domain_terms_replace_lossy_model_paraphrases():
    analyzer = RequirementAnalyzer()

    functional, _, _ = analyzer._preserve_uncovered_clauses(
        [
            "Register artifacts and treatment recipes.",
            "Pause process cycles when environmental readings exceed defined thresholds.",
        ],
        [],
        [],
        (
            "Build a workflow where reviewers register records and reversible procedures, "
            "pause process cycles when readings leave the reviewer-defined envelope."
        ),
        None,
    )

    assert "Reviewers register records and reversible procedures." in functional
    assert "Pause process cycles when readings leave the reviewer-defined envelope." in functional


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


def test_unknown_extraction_preserves_details_without_keyword_filler(monkeypatch):
    analyzer = RequirementAnalyzer()
    model_output = {
        "domain": "Specialized observation workflow",
        "summary": "Reviewers coordinate instrument observations and provenance.",
        "functional_requirements": [
            "Reviewers can record samples.",
            "System ingests humidity readings from instrument controllers.",
            "Continue operating offline before synchronization.",
        ],
        "non_functional_requirements": [
            "Offline operation protects workflow continuity.",
            "Continue operating offline before synchronization.",
            "Preserve tamper-evident provenance.",
            "No cloud dependency.",
        ],
        "actors": ["Reviewer", "Instrument Controller", "Provenance Manager"],
        "domain_entities": ["Sample", "Humidity Reading"],
        "domain_workflows": ["Record Samples", "Ingest Humidity Readings"],
        "integrations": [],
        "data_characteristics": [],
        "explicit_constraints": [],
        "assumptions": [],
        "open_questions": ["What latency target is required?"],
    }
    monkeypatch.setattr(
        analyzer.ai_client, "generate", lambda *args, **kwargs: model_output
    )

    result = analyzer.analyze(
        title="Observation Coordination",
        description=(
            "Reviewers record samples, ingest humidity readings from instrument controllers, "
            "preserve tamper-evident provenance, and continue offline before synchronizing. "
            "Do not assume a cloud provider, users, latency, availability, or retention."
        ),
        business_context="Support careful review without hiding unresolved decisions.",
        answers={"budget": "unknown", "preferred_cloud": "No preference"},
    )

    assert result.analysis_source == "ollama-pretrained"
    assert not any("explicitly mentioned" in item for item in result.functional_requirements)
    assert not any("do not assume" in item.lower() for item in result.non_functional_requirements)
    assert not any("cloud" in item.lower() for item in result.non_functional_requirements)
    assert [actor.name for actor in result.actors] == ["Reviewer", "Instrument Controller"]
    assert [workflow.description for workflow in result.domain_workflows] == result.functional_requirements
    assert any("Instrument or sensor" in item for item in result.data_characteristics)
    assert any("availability" in item.lower() for item in result.open_questions)
    assert any("retained" in item.lower() for item in result.open_questions)
    functional_keys = {
        " ".join(re.findall(r"[a-z0-9]+", item.casefold()))
        for item in result.functional_requirements
    }
    assert not functional_keys.intersection(
        " ".join(re.findall(r"[a-z0-9]+", item.casefold()))
        for item in result.non_functional_requirements
    )
    assert not any("unresolved decisions" in item.lower() for item in result.constraints)
    assert not any("budget posture" in item.lower() for item in result.constraints)


def test_explicit_quality_clauses_replace_redundant_model_paraphrases():
    analyzer = RequirementAnalyzer()

    result = analyzer._merge_explicit_items(
        [
            "Maintain tamper-evident treatment provenance.",
            "Preservation of treatment provenance",
            "Continue working offline on tablets before synchronizing.",
        ],
        [
            "Maintain tamper-evident treatment provenance.",
            "Continue working offline on tablets before synchronizing.",
        ],
    )

    assert result == [
        "Maintain tamper-evident treatment provenance.",
        "Continue working offline on tablets before synchronizing.",
    ]


def test_unknown_workflow_names_and_centralization_guard_are_conservative():
    analyzer = RequirementAnalyzer()

    assert analyzer._workflow_name(
        "Process cycles can be paused when readings leave the allowed envelope."
    ) == "Pause Process Cycles"
    assert analyzer._workflow_name(
        "Treatment provenance is maintained with tamper evidence."
    ) == "Maintain Treatment Provenance"
    assert analyzer._unsupported_characteristics(
        "Synchronize with a central server.",
        "Continue offline before synchronizing.",
    ) == ["centralized synchronization"]
