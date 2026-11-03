"""HNSW index on memory embeddings (B3 / O2).

Exact distance search compares the query against every current embedding of the tenant, so the
vector channel grows linearly with the tenant. The index only helps the nearest-first query shape
(``infrastructure/retrieval.py``); the planner still chooses between index and sequential scan.

Cost: the index is roughly the size of the vector column again, and every insert/update of an
embedding maintains it. On an existing deployment build it in a maintenance window
(``CREATE INDEX CONCURRENTLY`` cannot run inside a migration transaction) and drop it again with
``DROP INDEX ix_memory_embeddings_hnsw`` if the deployment runs pgvector < 0.8, where the provider
falls back to exact scans and the index would only cost writes.
"""
from alembic import op

revision = "0014_vector_hnsw_index"
down_revision = "0013_job_priority"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX ix_memory_embeddings_hnsw ON memory_embeddings "
        "USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)"
    )


def downgrade() -> None:
    op.drop_index("ix_memory_embeddings_hnsw", table_name="memory_embeddings")
