"""Index (tenant, content_hash) so identical content can be found for embedding reuse (O4)."""
from alembic import op

revision = "0011_content_hash_index"
down_revision = "0010_stored_lexical_vectors"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_memory_versions_tenant_content_hash", "memory_versions", ["tenant_id", "content_hash"]
    )


def downgrade() -> None:
    op.drop_index("ix_memory_versions_tenant_content_hash", table_name="memory_versions")
