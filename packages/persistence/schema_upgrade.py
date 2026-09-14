"""Additive schema upgrades for tables that predate a feature.

The project creates tables with ``Base.metadata.create_all``, which never alters
an existing table. Role discovery adds provenance columns to ``jobs``, so those
columns are added here on startup. Only additive, nullable columns belong in this
module; anything destructive needs a real migration.
"""

from typing import Dict, List, Tuple

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncConnection

# table -> [(column, DDL type, default clause)]
ADDITIVE_COLUMNS: Dict[str, List[Tuple[str, str, str]]] = {
    "jobs": [
        ("discovered_by", "VARCHAR(50)", "'discovery-cycle'"),
        ("search_query_id", "VARCHAR(36)", ""),
        ("search_provider", "VARCHAR(50)", ""),
        ("source_url", "TEXT", ""),
        ("description_fingerprint", "VARCHAR(64)", ""),
        ("match_score", "INTEGER", ""),
        ("scorecard", "JSON", ""),
    ],
    "application_runs": [
        ("applied_at", "TIMESTAMP", ""),
        ("submitted_manually", "BOOLEAN", "FALSE"),
        ("outcome_history", "JSON", ""),
    ],
}


async def apply_additive_migrations(conn: AsyncConnection) -> List[str]:
    """Adds any missing columns. Returns the DDL statements that ran."""
    applied: List[str] = []

    def _existing(sync_conn, table: str) -> List[str]:
        inspector = inspect(sync_conn)
        if table not in inspector.get_table_names():
            return []
        return [column["name"] for column in inspector.get_columns(table)]

    for table, columns in ADDITIVE_COLUMNS.items():
        existing = await conn.run_sync(_existing, table)
        if not existing:
            continue  # create_all will build the table with every column already
        for name, ddl_type, default in columns:
            if name in existing:
                continue
            statement = f"ALTER TABLE {table} ADD COLUMN {name} {ddl_type}"
            if default:
                statement += f" DEFAULT {default}"
            await conn.execute(text(statement))
            applied.append(statement)

    return applied
