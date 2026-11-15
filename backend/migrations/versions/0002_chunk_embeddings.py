"""Enable pgvector and add nullable embeddings for existing chunks."""

from alembic import op
from pgvector.sqlalchemy import Vector
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    # SQLite's JSON variant exists only for the offline test suite. Application
    # configuration accepts PostgreSQL, where this is a native pgvector column.
    with op.batch_alter_table("code_chunks") as batch:
        batch.add_column(sa.Column(
            "embedding", Vector().with_variant(sa.JSON(none_as_null=True), "sqlite"), nullable=True,
        ))
        batch.add_column(sa.Column("embedding_model", sa.Text(), nullable=True))
        batch.add_column(sa.Column("embedding_key", sa.String(64), nullable=True))
        batch.create_check_constraint(
            "ck_code_chunks_embedding_metadata",
            "(embedding IS NULL AND embedding_model IS NULL AND embedding_key IS NULL) OR "
            "(embedding IS NOT NULL AND embedding_model IS NOT NULL AND embedding_key IS NOT NULL)",
        )


def downgrade() -> None:
    with op.batch_alter_table("code_chunks") as batch:
        batch.drop_constraint("ck_code_chunks_embedding_metadata", type_="check")
        batch.drop_column("embedding_key")
        batch.drop_column("embedding_model")
        batch.drop_column("embedding")
    # Leave the extension installed: other tables may also use it.
