from app.schemas.domain import ProjectAction, WorkspaceEditRequest


class ProjectActionService:
    """Translate typed project actions into the canonical workspace edit contract."""

    _TARGETS = {
        "actor": "actor",
        "entity": "domain_entity",
        "architecture_component": "architecture_component",
        "api_endpoint": "api_endpoint",
        "database_entity": "database_entity",
        "prototype_screen": "prototype_screen",
    }

    def to_workspace_edit(
        self,
        action: ProjectAction,
        *,
        expected_updated_at=None,
    ) -> WorkspaceEditRequest | None:
        if action.action in {"undo", "redo", "regenerate_affected"}:
            return None
        if action.action == "update_deployment":
            return WorkspaceEditRequest(
                target_type="deployment",
                operation="update",
                target_id=action.target_id or "deployment",
                value=action.value,
                expected_updated_at=expected_updated_at,
            )
        if action.action == "update_prototype":
            return WorkspaceEditRequest(
                target_type="prototype_theme",
                operation="update",
                target_id=action.target_id or "theme",
                value=action.value,
                expected_updated_at=expected_updated_at,
            )
        if "requirement" in action.action:
            operation = action.action.split("_", 1)[0]
            return WorkspaceEditRequest(
                target_type=action.requirement_type,
                operation=operation,
                target_id=action.target_id,
                value=action.value,
                expected_updated_at=expected_updated_at,
            )
        operation = "delete" if action.action.startswith(("delete_", "remove_")) else action.action.split("_", 1)[0]
        suffix = action.action.removeprefix(f"{operation}_")
        if action.action == "remove_prototype_screen":
            suffix = "prototype_screen"
        target = self._TARGETS.get(suffix)
        if target is None:
            raise ValueError(f"Unsupported project action: {action.action}")
        return WorkspaceEditRequest(
            target_type=target,
            operation=operation,
            target_id=action.target_id,
            parent_id=action.parent_id,
            value=action.value,
            expected_updated_at=expected_updated_at,
        )
