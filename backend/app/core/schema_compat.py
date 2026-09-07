from sqlalchemy import JSON, inspect, text
from sqlalchemy.engine import Engine


def ensure_workspace_columns(engine: Engine) -> None:
    """Add additive workspace columns for databases created before this release."""

    inspector = inspect(engine)
    if "workspaces" not in inspector.get_table_names():
        return

    existing = {column["name"] for column in inspector.get_columns("workspaces")}
    json_type = JSON().compile(dialect=engine.dialect)
    additions = {
        "causal_graph_json": json_type,
        "adrs_json": json_type,
        "diagram_layouts_json": json_type,
        "edit_history_json": json_type,
    }
    with engine.begin() as connection:
        for column_name, column_type in additions.items():
            if column_name not in existing:
                connection.execute(
                    text(
                        f'ALTER TABLE workspaces ADD COLUMN "{column_name}" {column_type}'
                    )
                )
