"""Store the lexical document vectors instead of recomputing them for every row of every query.

Measured (docs/optimization/measurements/b2-*): the english channel evaluated
``to_tsvector('english', content)`` on every candidate row per search, 0.6-1.9 s for 10^4 rows.
Adding a GIN index does NOT help the application role: ``memory_versions`` is under FORCE ROW LEVEL
SECURITY and PostgreSQL only pushes *leakproof* user quals below an RLS policy; the text-search
match functions (ts_match_vq & co) are not leakproof, so ``@@`` stays a post-filter and the
existing ``simple``/Chinese GIN indexes are not used by the app role either.  What we can do
without weakening RLS is move the expensive part to write time: version rows are immutable, so a
STORED generated column is computed once and the query only runs the cheap match/rank.

Operational notes
  * ADD COLUMN ... GENERATED ... STORED rewrites the table under an ACCESS EXCLUSIVE lock
    (about 6 s per 10^4 rows with ~850-byte bodies on the 2-core test sandbox). Schedule it.
  * Each column roughly doubles the text storage of the table (tsvector ~ size of the body).
  * No GIN index is added on purpose: the app role could not use it and it would slow writes.
"""
from alembic import op

revision = "0010_stored_lexical_vectors"
down_revision = "0009_job_notify"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE memory_versions ADD COLUMN lexical_en tsvector "
        "GENERATED ALWAYS AS (to_tsvector('english'::regconfig, content)) STORED"
    )
    op.execute(
        "ALTER TABLE memory_versions ADD COLUMN lexical_zh tsvector "
        "GENERATED ALWAYS AS (to_tsvector('simple'::regconfig, memory_lexical_tokens(content))) "
        "STORED"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE memory_versions DROP COLUMN lexical_zh")
    op.execute("ALTER TABLE memory_versions DROP COLUMN lexical_en")
