"""Functional / non-functional / constraint classification, measured.

The classifier is deterministic, so its accuracy is a property of the code and
can be measured rather than asserted. `LABELLED_STATEMENTS` below is a
hand-labelled benchmark: each statement is tagged with what a requirements
engineer would call it, independent of what the code currently does. The
benchmark is committed so the number is reproducible and a regression shows up
as a failing test rather than as a quietly worse model.

Each defect it exposed has its own test underneath, so a fix is pinned by a
named case and not only by the aggregate score.
"""

import pytest

from app.services.requirement_analyzer import RequirementAnalyzer

# F = functional (a domain action someone performs)
# N = non-functional (a measurable quality of the system)
# C = constraint (a hard limit imposed from outside the solution)
LABELLED_STATEMENTS: list[tuple[str, str]] = [
    # -------------------------------------------------- functional behaviour
    ("Drivers can search for nearby charging stations.", "F"),
    ("Operators update charger availability.", "F"),
    ("Customers upload a prescription for pharmacist review.", "F"),
    ("Instructors publish courses and lessons.", "F"),
    ("Graders score submissions.", "F"),
    ("Dispatchers assign shipments to carriers.", "F"),
    ("Admins review analytics dashboards.", "F"),
    ("Support cancellation of an existing booking.", "F"),
    ("Refund flows for a cancelled booking.", "F"),
    ("Generate an invoice when a session completes.", "F"),
    ("Display live bay availability for each depot.", "F"),
    ("Show which chargers are available at a station.", "F"),
    ("Track the status of a charging session.", "F"),
    ("Approve a change request before deployment.", "F"),
    ("Register a new sensor device.", "F"),
    ("Export a monthly settlement report.", "F"),
    ("Notify the customer when the order ships.", "F"),
    ("Book a slot for a specific connector type.", "F"),
    ("Transfer funds between two accounts.", "F"),
    ("Capture proof of delivery at the drop-off point.", "F"),
    # A domain action with a modal is still an action, not a constraint.
    ("Operators must approve refunds above the review threshold.", "F"),
    # ------------------------------------------------- measurable qualities
    ("The service must meet a 99.95% availability target.", "N"),
    ("API responses should complete within 200 ms at the 95th percentile.", "N"),
    ("The platform must support 200,000 concurrent users.", "N"),
    ("All data at rest must be encrypted.", "N"),
    ("The system should remain usable offline for up to 24 hours.", "N"),
    ("Audit logs must be retained for 10 years.", "N"),
    ("Recovery time objective is 15 minutes.", "N"),
    ("The interface must meet WCAG 2.1 AA accessibility.", "N"),
    ("Provide observability across all services.", "N"),
    ("Maintain data integrity across concurrent writes.", "N"),
    ("The platform must be resilient to a single node failure.", "N"),
    ("Support high volumes of telemetry ingestion.", "N"),
    ("Latency between the edge device and the gateway must stay under 50 ms.", "N"),
    ("Backups must run nightly with verified restores.", "N"),
    ("The system must scale to 5 million events per day.", "N"),
    # ------------------------------------------------------- hard constraints
    ("Must use PostgreSQL as the primary datastore.", "C"),
    ("The application must run in an in-country region only.", "C"),
    ("Cannot use any managed cloud queue service.", "C"),
    ("Must comply with GDPR data residency regulation.", "C"),
    ("Financial postings must be strongly consistent.", "C"),
    ("Must deploy to Azure only.", "C"),
    ("The build shall use Java 17.", "C"),
    ("Must not use third-party analytics SDKs.", "C"),
]

# The score the classifier is known to reach. Raise it when the classifier
# genuinely improves; never lower it to make a regression pass.
MINIMUM_ACCURACY = 1.0


def classify(statement: str) -> str:
    """The bucket the classifier puts a statement in.

    Every statement is fed in as *functional*, which is the hardest direction:
    the classifier has to pull qualities and constraints out on its own rather
    than being handed the answer by the caller's label.
    """
    functional, non_functional, constraints = RequirementAnalyzer()._reclassify_requirements(
        [statement], [], []
    )
    if statement in functional:
        return "F"
    if statement in non_functional:
        return "N"
    if statement in constraints:
        return "C"
    return "?"


@pytest.mark.parametrize(
    "statement,expected",
    LABELLED_STATEMENTS,
    ids=[statement[:48] for statement, _ in LABELLED_STATEMENTS],
)
def test_each_labelled_statement_is_classified_correctly(statement, expected):
    assert classify(statement) == expected


def test_overall_accuracy_does_not_regress():
    """The aggregate, reported as a number rather than claimed."""
    correct = sum(
        classify(statement) == expected for statement, expected in LABELLED_STATEMENTS
    )
    accuracy = correct / len(LABELLED_STATEMENTS)
    assert accuracy >= MINIMUM_ACCURACY, (
        f"{correct}/{len(LABELLED_STATEMENTS)} = {accuracy:.1%}, "
        f"below the recorded {MINIMUM_ACCURACY:.0%}"
    )


# --------------------------------------------------------------- named defects


def test_a_mandated_technology_labelled_functional_becomes_a_constraint():
    """The constraint branch used to require a quality word first.

    `if quality_hits and _solution_constraint(item)` meant a statement with no
    quality word in it at all — "Must use PostgreSQL as the primary datastore."
    — stayed functional forever, along with every other mandated technology,
    region or platform the extractor happened to label functional. Constraint
    recall on this benchmark was 2/8 because of that one condition.
    """
    assert classify("Must use PostgreSQL as the primary datastore.") == "C"
    assert classify("Must deploy to Azure only.") == "C"
    assert classify("Cannot use any managed cloud queue service.") == "C"


def test_a_domain_action_with_a_modal_is_not_pulled_into_constraints():
    """The guard that makes widening the branch above safe.

    `_solution_constraint` is an AND of two independent signals: a hard modal
    AND a solution-space marker. An action with a modal matches no solution
    marker, so it stays functional.
    """
    assert classify("Operators must approve refunds above the review threshold.") == "F"
    assert classify("Customers must confirm a booking before payment.") == "F"


def test_a_cadence_is_not_a_deployment_constraint():
    """"must run" is a placement marker because "must run on Kubernetes" is a
    deployment constraint. It is matched as a substring, so "Backups must run
    nightly with verified restores." matched it too and a recoverability
    quality was filed as a solution constraint."""
    assert classify("Backups must run nightly with verified restores.") == "N"
    assert classify("Reconciliation must run hourly.") != "C"
    # But a real placement constraint still is one.
    assert classify("The service must run on Kubernetes only.") == "C"


def test_a_capability_about_availability_stays_functional():
    """"availability" is a quality word, but showing a resource's availability
    is a feature. Without this, "Display live bay availability" became an
    NFR."""
    assert classify("Display live bay availability for each depot.") == "F"
    assert classify("Show which chargers are available at a station.") == "F"
    # The quality reading of the same word is still an NFR.
    assert classify("The service must meet a 99.95% availability target.") == "N"
