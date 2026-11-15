"""Create repositories and code chunks."""

from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "repositories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("path"),
    )
    op.create_table(
        "code_chunks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("repository_id", sa.Integer(), sa.ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("start_line", sa.Integer(), nullable=False),
        sa.Column("end_line", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.CheckConstraint("start_line >= 1", name="ck_code_chunks_start_line"),
        sa.CheckConstraint("end_line >= start_line", name="ck_code_chunks_end_line"),
    )
    op.create_index("ix_code_chunks_repository_id", "code_chunks", ["repository_id"])


def downgrade() -> None:
    op.drop_index("ix_code_chunks_repository_id", table_name="code_chunks")
    op.drop_table("code_chunks")
    op.drop_table("repositories")
