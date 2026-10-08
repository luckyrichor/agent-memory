"""Correction provenance, tenant-bound successor, indexed Chinese bigram channel."""

from alembic import op

revision = "0007_review_hardening"
down_revision = "0006_embedding_1024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE memory_versions ADD COLUMN reason varchar(512)")
    op.execute("ALTER TABLE memories ADD COLUMN successor_id uuid")
    op.execute("""ALTER TABLE memories ADD CONSTRAINT fk_memory_successor
        FOREIGN KEY (tenant_id, successor_id) REFERENCES memories(tenant_id, memory_id)""")
    op.execute(
        "CREATE INDEX ix_idempotency_retention ON idempotency_records(tenant_id, created_at)"
    )
    op.execute("""CREATE FUNCTION memory_lexical_tokens(input text) RETURNS text
    LANGUAGE plpgsql IMMUTABLE STRICT PARALLEL SAFE AS $$
    DECLARE part text[]; word text; result text := ''; i integer;
    BEGIN
      FOR part IN SELECT regexp_matches(lower(input), '[一-鿿]+|[a-z0-9_]+', 'g') LOOP
        word := part[1];
        IF word ~ '[一-鿿]' AND length(word) > 1 THEN
          FOR i IN 1..length(word)-1 LOOP
            result := result || ' ' || substr(word, i, 2);
          END LOOP;
        ELSE result := result || ' ' || word;
        END IF;
      END LOOP;
      RETURN result;
    END $$""")
    op.execute("""CREATE INDEX ix_memory_versions_chinese_lexical ON memory_versions
        USING gin(to_tsvector('simple', memory_lexical_tokens(content)))""")


def downgrade() -> None:
    op.execute("DROP INDEX ix_memory_versions_chinese_lexical")
    op.execute("DROP FUNCTION memory_lexical_tokens(text)")
    op.execute("DROP INDEX ix_idempotency_retention")
    op.execute("ALTER TABLE memories DROP CONSTRAINT fk_memory_successor")
    op.execute("ALTER TABLE memories DROP COLUMN successor_id")
    op.execute("ALTER TABLE memory_versions DROP COLUMN reason")
