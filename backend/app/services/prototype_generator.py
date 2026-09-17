import hashlib
import re
from datetime import datetime, timezone

from app.schemas.domain import (
    ApiDesign,
    DatabaseDesign,
    PrototypeAction,
    PrototypeComponent,
    PrototypeRole,
    PrototypeScreen,
    PrototypeSpec,
    PrototypeTheme,
    RequirementModel,
)
from app.services.domain_inference import singularize


class PrototypeGenerator:
    """Build a safe, deterministic product prototype from canonical project facts."""

    _GROUPS = (
        ("account", {"login", "register", "authentication", "profile", "account"}),
        ("search", {"search", "find", "discover", "discovery", "browse", "nearby", "filter", "map"}),
        ("booking", {"book", "booking", "reserve", "reservation", "schedule", "appointment", "slot"}),
        ("payment", {"pay", "payment", "billing", "checkout", "refund", "invoice"}),
        ("monitoring", {"monitor", "tracking", "track", "realtime", "real-time", "status", "session", "telemetry", "alert"}),
        ("operations", {"manage", "operator", "admin", "maintain", "approve", "review", "assign", "update"}),
        ("reports", {"report", "analytics", "audit", "history", "insight"}),
    )
    _SCREEN_CONFIG = {
        "account": ("Account", "form", "form"),
        "search": ("Explore", "search", "search"),
        "booking": ("Bookings", "workflow", "form"),
        "payment": ("Payments", "workflow", "form"),
        "monitoring": ("Live status", "monitoring", "status"),
        "operations": ("Operations", "records", "table"),
        "reports": ("Reports", "records", "metrics"),
    }
    _GROUP_ORDER = {
        "account": 0,
        "search": 1,
        "booking": 2,
        "payment": 3,
        "monitoring": 4,
        "operations": 5,
        "reports": 6,
    }
    _STOP_WORDS = {
        "a", "an", "and", "are", "be", "can", "for", "from", "in", "of", "on",
        "or", "should", "system", "that", "the", "their", "to", "user", "users", "with",
    }

    def generate(
        self,
        *,
        project_id: str,
        title: str,
        requirements: RequirementModel,
        api_design: ApiDesign,
        database_design: DatabaseDesign,
        existing: PrototypeSpec | None = None,
    ) -> PrototypeSpec:
        requirement_rows = [
            (f"FR-{index:03d}", text)
            for index, text in enumerate(requirements.functional_requirements, start=1)
        ]
        actor_rows = [
            (
                actor.id or f"ACT-{index:03d}",
                actor.name,
                actor.description or "No additional actor description is defined.",
                actor.responsibilities,
            )
            for index, actor in enumerate(requirements.actors, start=1)
        ]
        # One role per actor identifier. Upstream now allocates collision-free
        # ids, but workspaces saved before that fix still hold duplicates, and a
        # duplicate here makes the role filter ambiguous and React render the
        # same key twice.
        roles: list[PrototypeRole] = []
        claimed_actor_ids: set[str] = set()
        for actor_id, name, description, _ in actor_rows:
            if actor_id in claimed_actor_ids:
                continue
            claimed_actor_ids.add(actor_id)
            roles.append(
                PrototypeRole(actor_id=actor_id, name=name, description=description)
            )
        grouped: dict[str, list[tuple[str, str]]] = {}
        for req_id, text in requirement_rows:
            for group in self._groups_for(text):
                grouped.setdefault(group, []).append((req_id, text))

        theme = self._theme(requirements)
        screens: list[PrototypeScreen] = [
            self._overview_screen(title, requirements, requirement_rows, actor_rows, theme)
        ]
        ordered_groups = sorted(
            grouped.items(),
            key=lambda item: (
                self._GROUP_ORDER.get(item[0], len(self._GROUP_ORDER)),
                min(int(req_id.split("-")[1]) for req_id, _ in item[1]),
            ),
        )
        # NOTE: deduplicating screens by their requirement set was tried and
        # reverted. A requirement legitimately belongs to several capability
        # groups — a booking requirement is both the booking screen and the
        # payment screen — so dropping the later group deleted real screens
        # (Bookings and Payments both vanished from a seeded project). The
        # occasional redundant screen is a smaller defect than a missing one.
        for group, rows in ordered_groups:
            screens.append(
                self._requirement_screen(
                    group,
                    rows,
                    actor_rows,
                    requirements,
                    database_design,
                )
            )

        existing_by_id = {screen.id: screen for screen in existing.screens} if existing else {}
        dismissed = set(existing.dismissed_screen_ids) if existing else set()
        merged: list[PrototypeScreen] = []
        for screen in screens:
            if screen.id in dismissed:
                continue
            previous = existing_by_id.get(screen.id)
            if previous:
                screen.visual_overrides = dict(previous.visual_overrides)
                if previous.visual_overrides.get("name"):
                    screen.name = previous.visual_overrides["name"]
                component_titles = {
                    key.removeprefix("component:"): value
                    for key, value in previous.visual_overrides.items()
                    if key.startswith("component:")
                }
                for component in screen.components:
                    if component.id in component_titles:
                        component.title = component_titles[component.id]
            merged.append(screen)

        if existing:
            generated_ids = {screen.id for screen in screens}
            merged.extend(
                screen
                for screen in existing.screens
                if screen.id not in generated_ids
                and screen.visual_overrides.get("custom") == "true"
                and screen.id not in dismissed
            )

        self._add_navigation_actions(merged)
        warnings: list[str] = []
        if not roles:
            warnings.append(
                "No validated actors are available. Screens remain unassigned until actors are confirmed."
            )
        if not requirement_rows:
            warnings.append(
                "No functional requirements are available, so only a project overview can be represented."
            )
        if requirements.open_questions:
            warnings.append(
                f"{len(requirements.open_questions)} unresolved project question(s) may limit prototype detail."
            )
        start_screen_id = merged[0].id
        return PrototypeSpec(
            id=existing.id if existing else f"PROTO-{project_id}",
            project_id=project_id,
            version="1",
            title=f"{title} prototype",
            domain=requirements.domain,
            theme=existing.theme if existing else theme,
            roles=roles,
            screens=merged,
            start_screen_id=(
                existing.start_screen_id
                if existing and existing.start_screen_id in {item.id for item in merged}
                else start_screen_id
            ),
            dismissed_screen_ids=sorted(dismissed),
            warnings=warnings,
            generated_at=datetime.now(timezone.utc),
        )

    def _overview_screen(
        self,
        title: str,
        requirements: RequirementModel,
        rows: list[tuple[str, str]],
        actors: list[tuple[str, str, str, list[str]]],
        theme: PrototypeTheme,
    ) -> PrototypeScreen:
        requirement_ids = [item[0] for item in rows[:6]]
        actor_ids = [item[0] for item in actors]
        items = [self._sentence(text, 100) for _, text in rows[:5]]
        if not items:
            items = ["No validated product capabilities are defined yet."]
        status_items = []
        if theme.realtime:
            status_items.append("Live updates enabled by a confirmed realtime requirement")
        if theme.offline:
            status_items.append("Offline and synchronization state")
        components = [
            PrototypeComponent(
                id="PROTO-COMP-OVERVIEW",
                component_type="hero",
                title=title,
                description=requirements.summary,
                items=items,
                source_requirement_ids=requirement_ids,
            )
        ]
        if status_items:
            components.append(
                PrototypeComponent(
                    id="PROTO-COMP-SYSTEM-STATE",
                    component_type="notice",
                    title="System state",
                    items=status_items,
                    source_requirement_ids=self._nfr_ids(requirements, {"realtime", "real-time", "offline", "sync"}),
                )
            )
        return PrototypeScreen(
            id="PROTO-SCREEN-OVERVIEW",
            name="Overview",
            route="/overview",
            purpose="Introduces the validated product scope and its primary capabilities.",
            layout="overview",
            actor_ids=actor_ids,
            components=components,
            states=self._states(requirements),
            source_requirement_ids=requirement_ids,
            source_actor_ids=actor_ids,
        )

    def _requirement_screen(
        self,
        group: str,
        rows: list[tuple[str, str]],
        actors: list[tuple[str, str, str, list[str]]],
        requirements: RequirementModel,
        database_design: DatabaseDesign,
    ) -> PrototypeScreen:
        req_ids = [item[0] for item in rows]
        texts = [item[1] for item in rows]
        if group.startswith("capability-"):
            name = self._capability_name(texts[0])
            layout = "workflow"
            component_type = "details"
        else:
            name, layout, component_type = self._SCREEN_CONFIG[group]
        screen_id = f"PROTO-SCREEN-{self._slug(group)}"
        actor_ids = self._actor_ids_for(texts, actors)
        entity_ids = self._entity_ids_for(texts, requirements)
        entity_names = [
            entity.name
            for index, entity in enumerate(requirements.domain_entities, start=1)
            if (entity.id or f"ENT-{index:03d}") in entity_ids
        ]
        fields = self._fields_for(group, entity_names, database_design)
        actions = [
            PrototypeAction(
                id=f"PROTO-ACTION-{self._slug(req_id)}",
                label=self._action_label(text),
                action_type=self._action_type(group, text),
                feedback="Prototype interaction completed. No external service was called.",
                source_requirement_ids=[req_id],
            )
            for req_id, text in rows[:6]
        ]
        # The first action is rendered as the screen's primary button, so a
        # real capability has to come before a topic-shaped fallback. The
        # fallback is the bare label "Open" — note that `_looks_actionable`
        # cannot be used for this, because "open" is itself an action verb, so
        # the fallback would test as actionable. A genuine open instruction
        # ("Open a ticket") carries an object and is unaffected. Sort is stable,
        # so requirement order is preserved within each bucket.
        actions.sort(key=lambda action: 1 if action.label.strip() == self._FALLBACK_ACTION else 0)
        component = PrototypeComponent(
            id=f"PROTO-COMP-{self._slug(group)}",
            component_type=component_type,
            title=name,
            description=" ".join(self._sentence(text, 160) for text in texts[:3]),
            fields=fields,
            items=[self._sentence(text, 110) for text in texts[:6]],
            actions=actions,
            source_requirement_ids=req_ids,
            source_entity_ids=entity_ids,
        )
        if group == "search" and any("map" in text.casefold() or "nearby" in text.casefold() for text in texts):
            component.items.append("Map and list presentation derived from location-oriented requirements")
        screen_states = self._states(requirements, texts)
        return PrototypeScreen(
            id=screen_id,
            name=name,
            route=f"/{self._slug(name)}",
            purpose="Represents: " + " ".join(self._sentence(text, 150) for text in texts[:3]),
            layout=layout,
            actor_ids=actor_ids,
            components=[
                component,
                *self._secondary_components(
                    group=group,
                    screen_name=name,
                    texts=texts,
                    req_ids=req_ids,
                    entity_ids=entity_ids,
                    entity_names=entity_names,
                    database_design=database_design,
                    states=screen_states,
                ),
            ],
            states=screen_states,
            source_requirement_ids=req_ids,
            source_actor_ids=actor_ids,
            source_entity_ids=entity_ids,
        )

    # What a screen needs beside its primary component to read as a real
    # screen. A search box with no result list is a control, not a page; a
    # booking form with nothing showing what is being booked and no sense of
    # where the reservation is in its lifecycle is a form, not a booking
    # experience. Each entry is (component_type, title suffix) in render order.
    _SCREEN_COMPOSITION: dict[str, tuple[tuple[str, str], ...]] = {
        "search": (("list", "Results"),),
        "booking": (("details", "Reservation summary"), ("timeline", "Interface states")),
        "payment": (("details", "Payment summary"),),
        "monitoring": (("timeline", "Interface states"),),
        "operations": (("metrics", "Operational totals"),),
        "reports": (("table", "Underlying records"),),
        "account": (("details", "Profile summary"),),
    }

    def _secondary_components(
        self,
        *,
        group: str,
        screen_name: str,
        texts: list[str],
        req_ids: list[str],
        entity_ids: list[str],
        entity_names: list[str],
        database_design: DatabaseDesign,
        states: list[str],
    ) -> list[PrototypeComponent]:
        """Compose the rest of the screen from recorded project data only.

        Every item below is read from the requirement model, the entity model
        or the screen's own states. Nothing here invents a record, a price, a
        count or a status value the project does not already hold.
        """
        plan = self._SCREEN_COMPOSITION.get(
            group, (("details", "Scope"),) if group.startswith("capability-") else ()
        )
        if not plan:
            return []

        displayable = self._fields_for(group, entity_names, database_design)
        entity_label = ", ".join(entity_names[:3]) if entity_names else ""
        components: list[PrototypeComponent] = []

        for component_type, suffix in plan:
            items: list[str]
            description: str
            if component_type == "list":
                # A results preview describes the shape of a record, which the
                # entity model really defines. It does not fabricate rows.
                items = displayable[:6] or [self._sentence(text, 110) for text in texts[:4]]
                description = (
                    f"Each result is one {entity_label} record, shown with the columns the "
                    f"data model defines."
                    if entity_label
                    else "Result rows follow the validated requirement scope."
                )
            elif component_type == "timeline":
                items = list(states)
                description = (
                    "Interface states this screen is required to represent. Domain status "
                    "values are not assumed."
                )
            elif component_type == "metrics":
                items = self._model_counts(entity_names, req_ids, database_design)
                description = "Counts taken from the current requirement and data model."
            elif component_type == "table":
                items = displayable[:6] or [self._sentence(text, 110) for text in texts[:4]]
                description = f"Records behind {screen_name.lower()}."
            else:  # details
                items = [self._sentence(text, 130) for text in texts[:4]]
                description = (
                    f"What this screen covers, traced to {', '.join(req_ids[:4])}."
                    if req_ids
                    else "Validated scope for this screen."
                )
            if not items:
                continue
            components.append(
                PrototypeComponent(
                    id=f"PROTO-COMP-{self._slug(group)}-{self._slug(component_type)}",
                    component_type=component_type,  # type: ignore[arg-type]
                    title=suffix,
                    description=description,
                    fields=displayable[:6] if component_type in {"table"} else [],
                    items=items,
                    actions=[],
                    source_requirement_ids=req_ids,
                    source_entity_ids=entity_ids,
                )
            )
        return components

    def _model_counts(
        self, entity_names: list[str], req_ids: list[str], database_design: DatabaseDesign
    ) -> list[str]:
        """Real counts from the model, phrased so they cannot read as live data."""
        counts: list[str] = []
        by_name = {entity.name: entity for entity in database_design.entities}
        for name in entity_names[:3]:
            entity = by_name.get(name)
            if entity is None:
                continue
            counts.append(f"{name}: {len(entity.fields)} modelled attributes")
        if req_ids:
            counts.append(f"{len(req_ids)} requirement(s) traced to this screen")
        return counts

    def _add_navigation_actions(self, screens: list[PrototypeScreen]) -> None:
        if not screens:
            return
        overview = screens[0]
        for screen in screens[1:7]:
            overview.components[0].actions.append(
                PrototypeAction(
                    id=f"PROTO-ACTION-NAV-{self._slug(screen.id)}",
                    label=f"Open {screen.name}",
                    action_type="navigate",
                    target_screen_id=screen.id,
                    source_requirement_ids=screen.source_requirement_ids,
                )
            )

    def _theme(self, requirements: RequirementModel) -> PrototypeTheme:
        text = " ".join([
            requirements.domain,
            *requirements.functional_requirements,
            *requirements.non_functional_requirements,
        ]).casefold()
        patterns = (
            ("scheduling", {"book", "reservation", "schedule", "appointment", "slot"}),
            ("monitoring", {"iot", "sensor", "monitor", "telemetry", "device", "realtime", "real-time"}),
            ("catalog", {"catalog", "cart", "marketplace", "product", "order"}),
            ("records", {"patient", "record", "case", "equipment", "maintenance", "document"}),
            ("workspace", {"developer", "repository", "deployment", "pipeline", "configuration"}),
        )
        pattern = next((name for name, markers in patterns if any(marker in text for marker in markers)), "workflow")
        nfr_text = " ".join(requirements.non_functional_requirements).casefold()
        accents = ("cyan", "emerald", "amber", "blue", "rose")
        accent = accents[int(hashlib.sha1(requirements.domain.encode()).hexdigest(), 16) % len(accents)]
        return PrototypeTheme(
            pattern=pattern,
            accent=accent,
            density="compact" if any(word in text for word in ("operator", "admin", "operations")) else "comfortable",
            accessible=any(word in nfr_text for word in ("accessibility", "accessible", "wcag")),
            realtime=any(word in text for word in ("realtime", "real-time", "live update", "live status")),
            offline=any(word in text for word in ("offline", "intermittent connectivity", "synchronization")),
        )

    def _groups_for(self, text: str) -> list[str]:
        tokens = self._tokens(text)
        groups = [
            name
            for name, markers in self._GROUPS
            if tokens & self._tokens(" ".join(markers))
            or any(marker in text.casefold() for marker in markers if "-" in marker)
        ]
        if groups:
            return groups
        digest = hashlib.sha1(text.casefold().encode()).hexdigest()[:8]
        return [f"capability-{digest}"]

    def _actor_ids_for(
        self,
        texts: list[str],
        actors: list[tuple[str, str, str, list[str]]],
    ) -> list[str]:
        requirement_tokens = self._tokens(" ".join(texts))
        matches = []
        for actor_id, name, _description, responsibilities in actors:
            actor_tokens = self._tokens(" ".join([name, *responsibilities]))
            if self._tokens(name) & requirement_tokens or len(actor_tokens & requirement_tokens) >= 2:
                matches.append(actor_id)
        if not matches and len(actors) == 1:
            matches.append(actors[0][0])
        return matches

    def _entity_ids_for(self, texts: list[str], requirements: RequirementModel) -> list[str]:
        tokens = self._tokens(" ".join(texts))
        output = []
        for index, entity in enumerate(requirements.domain_entities, start=1):
            if self._tokens(entity.name) & tokens:
                output.append(entity.id or f"ENT-{index:03d}")
        return output

    # Columns that exist for the database's benefit, not the user's. A form
    # asking someone to type an `Id` or an `Updated At` is not a form, and a
    # search screen filtering on `Created At` is not a filter.
    _SYSTEM_COLUMNS = {
        "id", "created_at", "updated_at", "deleted_at", "created_by",
        "updated_by", "version", "revision", "external_reference",
    }
    # Screens that show records rather than collect them can display audit
    # columns; screens that collect input cannot.
    _INPUT_GROUPS = {"account", "booking", "payment", "search"}

    def _field_label(self, column: str) -> str:
        """A user-facing label for a column.

        A foreign key is chosen from a picker, so it reads as the thing being
        chosen — `station_id` is offered as "Station", not "Station Id".
        """
        name = column[:-3] if column.endswith("_id") and column != "id" else column
        return name.replace("_", " ").strip().title()

    def _fields_for(self, group: str, entity_names: list[str], database_design: DatabaseDesign) -> list[str]:
        entity_tokens = self._tokens(" ".join(entity_names))
        if not entity_tokens:
            return []
        collects_input = group in self._INPUT_GROUPS or group.startswith("capability-")
        fields: list[str] = []
        for entity in database_design.entities:
            if not (self._tokens(entity.name) & entity_tokens):
                continue
            for field in entity.fields:
                if collects_input and field.name in self._SYSTEM_COLUMNS:
                    continue
                if field.name == "id":
                    continue
                fields.append(self._field_label(field.name))
        return list(dict.fromkeys(fields))[:8]

    def _states(self, requirements: RequirementModel, texts: list[str] | None = None) -> list[str]:
        source = " ".join([*(texts or []), *requirements.non_functional_requirements]).casefold()
        states = ["Loading", "Empty", "Error"]
        if any(word in source for word in ("realtime", "real-time", "live")):
            states.append("Live updating")
        if "offline" in source or "intermittent" in source:
            states.extend(["Offline", "Synchronizing"])
        return states

    def _nfr_ids(self, requirements: RequirementModel, markers: set[str]) -> list[str]:
        return [
            f"NFR-{index:03d}"
            for index, text in enumerate(requirements.non_functional_requirements, start=1)
            if any(marker in text.casefold() for marker in markers)
        ]

    def _capability_name(self, text: str) -> str:
        cleaned = re.sub(r"^(?:the\s+)?[^.]{0,40}?\b(?:can|must|should)\b\s*", "", text, flags=re.I)
        cleaned = re.sub(r"^(?:support|enable|allow|provide|manage)\s+", "", cleaned, flags=re.I)
        words = [word for word in re.findall(r"[A-Za-z0-9]+", cleaned) if word.casefold() not in self._STOP_WORDS]
        return " ".join(words[:5]).title() or "Product workflow"

    # The label used when a requirement names no action at all. Kept as a
    # constant because the screen's action ordering has to recognise it.
    _FALLBACK_ACTION = "Open"

    def _action_label(self, text: str) -> str:
        """A button label: a verb phrase the user could act on.

        "Drivers can reserve an available connector" is a requirement;
        "Reserve an available connector" is a button. A requirement that names
        no action at all — "EV charging booking platform" — cannot become a
        sensible label by truncation, so it is not used as one.
        """
        cleaned = re.sub(
            r"^(?:the\s+)?[^.]{0,50}?\b(?:can|must|should(?:\s+be\s+able\s+to)?)\b\s*",
            "", text, flags=re.I)
        # "Operators manage charger availability" has no modal verb, so strip a
        # leading plural actor noun instead and keep the verb it governs.
        cleaned = re.sub(
            r"^(?:users?|customers?|clients?|admins?|administrators?|operators?|"
            r"drivers?|staff|members?|managers?|owners?)\s+(?=[a-z])",
            "", cleaned, flags=re.I)
        cleaned = re.sub(r"^(?:support|enable|allow|provide)\s+", "", cleaned, flags=re.I)
        words = re.findall(r"[A-Za-z0-9'-]+", cleaned)
        label = " ".join(words[:6]).strip()
        if not label:
            return "Continue"
        # A label with no verb is a topic, not an action. Rather than print a
        # noun phrase on a button, say what the screen actually offers.
        if not self._looks_actionable(label):
            return self._FALLBACK_ACTION
        return label[:1].upper() + label[1:]

    # Verbs that make a label an instruction. Kept deliberately generic.
    _ACTION_VERBS = {
        "add", "apply", "approve", "assign", "book", "browse", "cancel",
        "change", "check", "choose", "complete", "confirm", "create",
        "delete", "download", "edit", "enter", "explore", "export", "filter",
        "find", "generate", "import", "invite", "list", "manage", "monitor",
        "open", "pay", "print", "publish", "rate", "refund", "register",
        "remove", "reschedule", "reserve", "review", "save", "search",
        "select", "send", "share", "sign", "start", "stop", "submit",
        "track", "update", "upload", "verify", "view",
    }

    def _looks_actionable(self, label: str) -> bool:
        return any(
            word.casefold().rstrip("s") in self._ACTION_VERBS
            or word.casefold() in self._ACTION_VERBS
            for word in re.findall(r"[A-Za-z]+", label)
        )

    @staticmethod
    def _action_type(group: str, text: str) -> str:
        lowered = text.casefold()
        if group == "search":
            return "filter" if "filter" in lowered else "submit"
        if any(word in lowered for word in ("view", "open", "details", "history")):
            return "open_dialog"
        if any(word in lowered for word in ("switch", "toggle", "start", "stop")):
            return "toggle"
        return "submit"

    @staticmethod
    def _sentence(value: str, limit: int) -> str:
        cleaned = " ".join(value.split()).strip()
        return cleaned if len(cleaned) <= limit else f"{cleaned[:limit - 3].rstrip()}..."

    @classmethod
    def _tokens(cls, value: str) -> set[str]:
        return {
            singularize(token)
            for token in re.findall(r"[a-z0-9-]+", value.casefold())
            if len(token) > 1 and token not in cls._STOP_WORDS
        }

    @staticmethod
    def _slug(value: str) -> str:
        return re.sub(r"[^A-Z0-9]+", "-", value.upper()).strip("-")[:70]
