"""add email login attempts

Revision ID: 291bfcd2d96a
Revises: 9e39a21ad11b
Create Date: 2026-08-04 16:45:36.524894

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '291bfcd2d96a'
down_revision: Union[str, None] = '9e39a21ad11b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # H3 brute-force counter: bound the number of wrong OTP guesses per code.
    # Existing codes get a default of 0.
    op.add_column(
        'email_login_codes',
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
    )


def downgrade() -> None:
    op.drop_column('email_login_codes', 'attempts')
