"""Ensure a current version belongs to its memory."""

from collections.abc import Sequence

from alembic import op

revision: str = "0002_current_version_integrity"
down_revision: str | None = "0001_memory_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("fk_memories_current_version", "memories", type_="foreignkey")
    op.create_unique_constraint(
        "uq_memory_versions_identity",
        "memory_versions",
        ["tenant_id", "memory_id", "memory_version_id"],
    )
    op.create_foreign_key(
        "fk_memories_current_version",
        "memories",
        "memory_versions",
        ["tenant_id", "memory_id", "current_version_id"],
        ["tenant_id", "memory_id", "memory_version_id"],
        deferrable=True,
        initially="DEFERRED",
    )


def downgrade() -> None:
    op.drop_constraint("fk_memories_current_version", "memories", type_="foreignkey")
    op.drop_constraint(
        "uq_memory_versions_identity",
        "memory_versions",
        type_="unique",
    )
    op.create_foreign_key(
        "fk_memories_current_version",
        "memories",
        "memory_versions",
        ["tenant_id", "current_version_id"],
        ["tenant_id", "memory_version_id"],
        deferrable=True,
        initially="DEFERRED",
    )
