"""Detection and removal of extraction artifacts in a stored requirement model.

Requirement extraction is fixed forward, but a requirement model is persisted
the moment a project is created — it is the source of truth and the user edits
it — so a project created before a fix keeps the artifact forever. The user sees
an unchanged diagram and reasonably concludes nothing was fixed.

This module finds only what can be shown to be wrong, by an exact test, and
never guesses:

  * A functional requirement that is, verbatim, the brief's opening sentence,
    where that sentence names the product rather than stating a requirement
    ("EV charging station booking platform for fast-growing metro cities in
    India."). It is the project description, not a requirement; downstream it
    became a workflow, an activity in the activity diagram, and a use case with
    no actor.
  * An actor whose name is an access-mechanism acronym compounded onto a role
    ("Sso Admin", "Rbac Admin"), or whose name no longer normalizes to a role
    at all ("USER", "USERS"). The first comes from the wizard's auth answer
    being read as a job title; the second from generic names the current
    validation rejects.

Detection is deterministic and reports what it found. It does not mutate
anything: removal happens only through the explicit, undoable
`repair_requirement_model` action, because the requirement model is the user's
data and a silent deletion is not an acceptable repair.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.schemas.domain import RequirementModel
from app.services.domain_inference import (
    _ACCESS_MECHANISM_TERMS,
    _is_product_title,
    _normalize_role,
    split_sentences,
    tokenize,
)


@dataclass
class RequirementArtifacts:
    """What in a stored requirement model can be shown to be an artifact."""

    title_requirements: list[str] = field(default_factory=list)
    invalid_actor_ids: list[str] = field(default_factory=list)
    invalid_actor_names: list[str] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.title_requirements) + len(self.invalid_actor_ids)

    def summary(self) -> str:
        parts: list[str] = []
        if self.title_requirements:
            parts.append(
                f"{len(self.title_requirements)} functional requirement(s) that repeat the "
                "project description rather than stating a requirement"
            )
        if self.invalid_actor_names:
            names = ", ".join(f"'{name}'" for name in self.invalid_actor_names)
            parts.append(f"{len(self.invalid_actor_names)} actor(s) that are not roles ({names})")
        return "; ".join(parts)


def _normalized(value: str) -> str:
    return " ".join(str(value or "").split()).casefold().rstrip(".")


def _actor_is_artifact(name: str) -> bool:
    """Whether an actor name can be shown not to be a role.

    Two exact tests, no judgement:

    1. It does not normalize to a role at all. `_normalize_role` returns empty
       for a name that is only a generic noun, so "USER" and "USERS" fail here
       while "Admin" — which the brief may genuinely name as a doer — does not.
    2. It contains an access-mechanism acronym. SSO, RBAC, MFA and OIDC are
       ways of proving who someone is; none of them is part of anybody's job
       title. These arrived from the wizard's auth answer ("OAuth2/OIDC; SSO;
       MFA; RBAC") being read as a modifier on whatever role noun followed.
    """
    if not str(name or "").strip():
        return True
    if not _normalize_role(name):
        return True
    return bool(set(tokenize(name)) & _ACCESS_MECHANISM_TERMS)


def detect_requirement_artifacts(
    requirements: RequirementModel,
    original_prompt: str | None,
) -> RequirementArtifacts:
    """Find the artifacts in a stored requirement model.

    `original_prompt` is the brief the project was created from. A requirement
    is only flagged when it matches that brief's own opening sentence verbatim,
    so a requirement the user wrote themselves is never touched even if it
    happens to read like a description.
    """
    found = RequirementArtifacts()

    sentences = split_sentences(original_prompt or "")
    if len(sentences) > 1 and _is_product_title(sentences[0]):
        title = _normalized(sentences[0])
        found.title_requirements = [
            requirement
            for requirement in requirements.functional_requirements
            if _normalized(requirement) == title
        ]

    for actor in requirements.actors:
        if _actor_is_artifact(actor.name):
            found.invalid_actor_ids.append(actor.id)
            found.invalid_actor_names.append(actor.name)

    return found


def remove_requirement_artifacts(
    requirements: RequirementModel,
    found: RequirementArtifacts,
) -> RequirementModel:
    """A copy of the model with the detected artifacts removed.

    Workflows naming a removed actor keep their description but lose the actor
    reference, rather than being deleted: the workflow is real, only its actor
    attribution was wrong. The diagram builders already say "Actor not
    confirmed" in that case, which is true, where the old name was not.
    """
    if not found.count:
        return requirements

    removed_requirements = {_normalized(value) for value in found.title_requirements}
    removed_actor_names = {_normalized(name) for name in found.invalid_actor_names}

    updated = requirements.model_copy(deep=True)
    updated.functional_requirements = [
        requirement
        for requirement in updated.functional_requirements
        if _normalized(requirement) not in removed_requirements
    ]
    updated.actors = [
        actor for actor in updated.actors if actor.id not in set(found.invalid_actor_ids)
    ]
    for workflow in updated.domain_workflows:
        if _normalized(workflow.primary_actor) in removed_actor_names:
            workflow.primary_actor = ""
    return updated
