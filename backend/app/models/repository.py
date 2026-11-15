"""Repository snapshots and their source chunks."""

from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Repository(Base):
    __tablename__ = "repositories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    path: Mapped[str] = mapped_column(Text, unique=True)
    indexed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CodeChunk(Base):
    __tablename__ = "code_chunks"
    __table_args__ = (
        CheckConstraint("start_line >= 1", name="ck_code_chunks_start_line"),
        CheckConstraint("end_line >= start_line", name="ck_code_chunks_end_line"),
        CheckConstraint(
            "(embedding IS NULL AND embedding_model IS NULL AND embedding_key IS NULL) OR "
            "(embedding IS NOT NULL AND embedding_model IS NOT NULL AND embedding_key IS NOT NULL)",
            name="ck_code_chunks_embedding_metadata",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    repository_id: Mapped[int] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"), index=True
    )
    file_path: Mapped[str] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
    start_line: Mapped[int] = mapped_column(Integer)
    end_line: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64))
    # Unconstrained vector dimension supports configurable models. Validation and
    # embedding_key keep vectors from different configurations separate.
    embedding: Mapped[list[float] | None] = mapped_column(Vector().with_variant(JSON(none_as_null=True), "sqlite"))
    embedding_model: Mapped[str | None] = mapped_column(Text)
    embedding_key: Mapped[str | None] = mapped_column(String(64))
