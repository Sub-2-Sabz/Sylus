"""add_unit_designs_table

Revision ID: 19b68e7b7945
Revises: b2c3d4e5f6a7
Create Date: 2026-10-28 19:15:39.136607

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '19b68e7b7945'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'unit_designs',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('nation_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('category', sa.String(length=50), nullable=False),
        sa.Column('components', sa.JSON(), nullable=False),
        sa.Column('stats', sa.JSON(), nullable=False),
        sa.Column('production_cost', sa.JSON(), nullable=False),
        sa.Column('upkeep', sa.JSON(), nullable=False),
        sa.Column('build_time', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['nation_id'], ['nations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_unit_designs_nation_id'), 'unit_designs', ['nation_id'], unique=False)
    op.create_index(op.f('ix_unit_designs_name'), 'unit_designs', ['name'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_unit_designs_name'), table_name='unit_designs')
    op.drop_index(op.f('ix_unit_designs_nation_id'), table_name='unit_designs')
    op.drop_table('unit_designs')
