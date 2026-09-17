"""Collision-free identifier allocation for the requirement model.

Identifiers such as ``ACT-001`` and ``ENT-001`` are the handles everything else
in the project addresses: the causal graph, API requirement citations, prototype
roles, traceability, and every assistant action that names an item. Two items
sharing one identifier is therefore not cosmetic — it makes "delete ACT-001"
ambiguous and lets a downstream lookup resolve to the wrong item.

The obvious way to mint one is from a position or a count::

    actor.id = actor.id or f"ACT-{index:03d}"        # positional
    Actor(id=f"ACT-{len(validated) + 1:03d}", ...)   # count

Both collide, because neither looks at what is already taken:

* positional — inserting an actor *before* an existing one gives the new actor
  the index the existing one already holds. Seen in practice: a project whose
  two actors, Driver and Operator, both ended up as ``ACT-001``.
* count — deleting an item lowers the count, so the next allocation reuses an
  identifier that a surviving item still holds.

``next_identifier`` and ``assign_missing_identifiers`` allocate from the set of
identifiers actually in use instead, so neither insertion nor deletion can
produce a duplicate.
"""

from __future__ import annotations

import re
from typing import Iterable, Sequence, TypeVar

_NUMERIC_SUFFIX = re.compile(r"^(?P<prefix>[A-Za-z][A-Za-z-]*)-(?P<number>\d+)$")

T = TypeVar("T")


def _taken_numbers(prefix: str, identifiers: Iterable[str]) -> set[int]:
    """Every number already used under ``prefix``, ignoring unrelated ids."""
    taken: set[int] = set()
    wanted = prefix.casefold()
    for identifier in identifiers:
        match = _NUMERIC_SUFFIX.match(str(identifier or "").strip())
        if match and match.group("prefix").casefold() == wanted:
            taken.add(int(match.group("number")))
    return taken


def next_identifier(prefix: str, existing: Iterable[str], *, width: int = 3) -> str:
    """The lowest ``<prefix>-<n>`` not already present in ``existing``.

    Reuses gaps left by deletions rather than growing without bound, and never
    returns an identifier that ``existing`` already contains.
    """
    taken = _taken_numbers(prefix, existing)
    number = 1
    while number in taken:
        number += 1
    return f"{prefix}-{number:0{width}d}"


def assign_missing_identifiers(
    items: Sequence[T],
    prefix: str,
    *,
    width: int = 3,
    attribute: str = "id",
) -> Sequence[T]:
    """Give every item in ``items`` a unique ``<prefix>-<n>`` identifier.

    Items that already carry one keep it. Items with none, and items whose
    identifier duplicates one held by an earlier item, are allocated the lowest
    free number. Mutates the items in place and returns them, so it can be
    dropped in where a positional assignment loop used to run.
    """
    used: set[str] = set()
    for item in items:
        current = str(getattr(item, attribute, "") or "").strip()
        if current and current not in used:
            # First holder of a given identifier keeps it.
            used.add(current)
            continue
        # Either it has no identifier, or an earlier item already holds this
        # one. Allocate from what is free rather than from a position.
        allocated = next_identifier(prefix, used, width=width)
        setattr(item, attribute, allocated)
        used.add(allocated)
    return items
