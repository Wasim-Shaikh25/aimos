"""add view and controls to organization_states

Revision ID: 90af4301da58
Revises: 291bfcd2d96a
Create Date: 2026-08-04 19:31:52.874691

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '90af4301da58'
down_revision: Union[str, None] = '291bfcd2d96a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("organization_states", schema=None) as batch_op:
        batch_op.add_column(sa.Column("view", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("controls", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("organization_states", schema=None) as batch_op:
        batch_op.drop_column("controls")
        batch_op.drop_column("view")
