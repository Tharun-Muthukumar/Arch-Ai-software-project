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
        roles = [
            PrototypeRole(actor_id=actor_id, name=name, description=description)
            for actor_id, name, description, _ in actor_rows
        ]
        grouped: dict[str, list[tuple[str, str]]] = {}
        for req_id, text in requirement_rows:
            for group in self._groups_for(text):
                grouped.setdefault(group, []).append((req_id, text))

        theme = self._theme(requirements)
        screens: list[PrototypeScreen] = [
            self._overview_screen(title, requirements, requirement_rows, actor_rows, theme)
        ]
        for group, rows in grouped.items():
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
        return PrototypeScreen(
            id=screen_id,
            name=name,
            route=f"/{self._slug(name)}",
            purpose="Represents: " + " ".join(self._sentence(text, 150) for text in texts[:3]),
            layout=layout,
            actor_ids=actor_ids,
            components=[component],
            states=self._states(requirements, texts),
            source_requirement_ids=req_ids,
            source_actor_ids=actor_ids,
            source_entity_ids=entity_ids,
        )

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

    def _fields_for(self, group: str, entity_names: list[str], database_design: DatabaseDesign) -> list[str]:
        if group not in {"account", "booking", "payment", "operations"}:
            return []
        entity_tokens = self._tokens(" ".join(entity_names))
        fields: list[str] = []
        for entity in database_design.entities:
            if not entity_tokens or not (self._tokens(entity.name) & entity_tokens):
                continue
            fields.extend(field.name.replace("_", " ").title() for field in entity.fields[:5])
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
        words = [word for word in re.findall(r"[A-Za-z0-9]+", cleaned) if word.casefold() not in self._STOP_WORDS]
        return " ".join(words[:5]).title() or "Product workflow"

    def _action_label(self, text: str) -> str:
        cleaned = re.sub(r"^(?:the\s+)?[^.]{0,50}?\b(?:can|must|should(?:\s+be\s+able\s+to)?)\b\s*", "", text, flags=re.I)
        words = re.findall(r"[A-Za-z0-9'-]+", cleaned)
        label = " ".join(words[:6]).strip()
        return (label[:1].upper() + label[1:]) if label else "Continue"

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
