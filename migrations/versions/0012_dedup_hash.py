"""Normalized-content hash on memory versions, for exact-duplicate detection of candidates (E2).

Backfill runs in the migration (owner connection, so RLS does not apply) in batches. On a large
table it is a long write; run it in a maintenance window.
"""
import hashlib
import unicodedata

import sqlalchemy as sa
from alembic import op

revision = "0012_dedup_hash"
down_revision = "0011_content_hash_index"
branch_labels = None
depends_on = None

BATCH = 1000


def dedup_hash(content: str) -> str:
    """Frozen copy of ``agent_memory.domain.dedup.dedup_hash`` as of this revision."""
    normalized = " ".join(unicodedata.normalize("NFKC", content).casefold().split())
    return hashlib.sha256(normalized.encode()).hexdigest()


PURGED_CONTENT_HASH = "0" * 64


def upgrade() -> None:
    op.add_column("memory_versions", sa.Column("dedup_hash", sa.String(64), nullable=True))
    connection = op.get_bind()
    while True:
        rows = connection.execute(
            sa.text(
                "SELECT tenant_id, memory_version_id, content FROM memory_versions "
                "WHERE dedup_hash IS NULL AND content_hash <> :purged LIMIT :n"
            ),
            {"purged": PURGED_CONTENT_HASH, "n": BATCH},
        ).all()
        if not rows:
            break
        connection.execute(
            sa.text(
                "UPDATE memory_versions SET dedup_hash = :h "
                "WHERE tenant_id = :t AND memory_version_id = :v"
            ),
            [{"h": dedup_hash(r.content), "t": r.tenant_id, "v": r.memory_version_id} for r in rows],
        )
    op.create_index(
        "ix_memory_versions_tenant_dedup_hash", "memory_versions", ["tenant_id", "dedup_hash"]
    )


def downgrade() -> None:
    op.drop_index("ix_memory_versions_tenant_dedup_hash", table_name="memory_versions")
    op.drop_column("memory_versions", "dedup_hash")
