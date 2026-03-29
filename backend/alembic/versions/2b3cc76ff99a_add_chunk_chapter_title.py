"""add_chunk_chapter_title

Revision ID: 2b3cc76ff99a
Revises: 
Create Date: 2026-03-25 00:25:31.978900
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector



# revision identifiers, used by Alembic.
revision = '2b3cc76ff99a'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = Inspector.from_engine(bind)

    existing = {col["name"] for col in inspector.get_columns("chunks")}
    if "chapter_title" not in existing:
        op.add_column("chunks", sa.Column("chapter_title", sa.String(), nullable=True))


def downgrade() -> None:
    pass
