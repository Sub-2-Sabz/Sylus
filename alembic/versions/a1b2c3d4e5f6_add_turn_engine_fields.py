"""Add turn engine fields to global_state

Revision ID: a1b2c3d4e5f6
Revises: 7fd1ef0fb4d6
Create Date: 2026-10-28 16:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '7fd1ef0fb4d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('global_state', sa.Column('is_paused', sa.Boolean(), server_default='0', nullable=False))
    op.add_column('global_state', sa.Column('map_channel_id', sa.BigInteger(), nullable=True))
    op.add_column('global_state', sa.Column('backup_channel_id', sa.BigInteger(), nullable=True))
    op.add_column('global_state', sa.Column('snapshot_interval_turns', sa.Integer(), server_default='5', nullable=False))


def downgrade() -> None:
    op.drop_column('global_state', 'snapshot_interval_turns')
    op.drop_column('global_state', 'backup_channel_id')
    op.drop_column('global_state', 'map_channel_id')
    op.drop_column('global_state', 'is_paused')
