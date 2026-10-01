"""Index PostgreSQL simple lexical documents (no Chinese segmentation claim)."""
from alembic import op

revision = "0005_lexical_index"
down_revision = "0004_embedding_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE INDEX ix_memory_versions_lexical ON memory_versions "
               "USING gin (to_tsvector('simple', content))")


def downgrade() -> None:
    op.drop_index("ix_memory_versions_lexical", table_name="memory_versions")
