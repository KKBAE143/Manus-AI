"""add_merge_job_progress

Revision ID: a1b2c3d4e5f6
Revises: 2b3cc76ff99a
Create Date: 2026-03-26 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector


revision = 'a1b2c3d4e5f6'
down_revision = '2b3cc76ff99a'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = Inspector.from_engine(bind)
    dialect = bind.dialect.name

    existing = {col["name"] for col in inspector.get_columns("merge_jobs")}
    if "progress_percent" not in existing:
        op.add_column("merge_jobs", sa.Column("progress_percent", sa.Float(), nullable=True))
    if "progress_message" not in existing:
        op.add_column("merge_jobs", sa.Column("progress_message", sa.String(), nullable=True))

    if dialect == "postgresql":
        try:
            op.execute(sa.text("ALTER TYPE mergestatus ADD VALUE IF NOT EXISTS 'in_progress'"))
        except Exception:
            pass


def downgrade() -> None:
    pass
