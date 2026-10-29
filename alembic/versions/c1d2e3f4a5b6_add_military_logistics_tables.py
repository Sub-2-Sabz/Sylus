"""add_military_logistics_tables

Revision ID: c1d2e3f4a5b6
Revises: 19b68e7b7945
Create Date: 2026-10-29 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c1d2e3f4a5b6'
down_revision: Union[str, Sequence[str], None] = '19b68e7b7945'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'military_production_queues',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('nation_id', sa.Integer(), nullable=False),
        sa.Column('province_id', sa.Integer(), nullable=False),
        sa.Column('design_id', sa.Integer(), nullable=False),
        sa.Column('facility_type', sa.String(length=50), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('completed_quantity', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('turns_remaining', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['nation_id'], ['nations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['province_id'], ['provinces.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['design_id'], ['unit_designs.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_military_production_queues_nation_id'), 'military_production_queues', ['nation_id'], unique=False)
    op.create_index(op.f('ix_military_production_queues_province_id'), 'military_production_queues', ['province_id'], unique=False)
    op.create_index(op.f('ix_military_production_queues_design_id'), 'military_production_queues', ['design_id'], unique=False)

    op.create_table(
        'military_formations',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('nation_id', sa.Integer(), nullable=False),
        sa.Column('province_id', sa.Integer(), nullable=False),
        sa.Column('design_id', sa.Integer(), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('experience', sa.Float(), nullable=False, server_default='10.0'),
        sa.Column('morale', sa.Float(), nullable=False, server_default='100.0'),
        sa.Column('fuel_supply', sa.Float(), nullable=False, server_default='1.0'),
        sa.Column('ammo_supply', sa.Float(), nullable=False, server_default='1.0'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['nation_id'], ['nations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['province_id'], ['provinces.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['design_id'], ['unit_designs.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_military_formations_nation_id'), 'military_formations', ['nation_id'], unique=False)
    op.create_index(op.f('ix_military_formations_province_id'), 'military_formations', ['province_id'], unique=False)
    op.create_index(op.f('ix_military_formations_design_id'), 'military_formations', ['design_id'], unique=False)

    op.create_table(
        'nation_intels',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('spy_nation_id', sa.Integer(), nullable=False),
        sa.Column('target_nation_id', sa.Integer(), nullable=False),
        sa.Column('intel_level', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('expires_at_turn', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['spy_nation_id'], ['nations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['target_nation_id'], ['nations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_nation_intels_spy_nation_id'), 'nation_intels', ['spy_nation_id'], unique=False)
    op.create_index(op.f('ix_nation_intels_target_nation_id'), 'nation_intels', ['target_nation_id'], unique=False)


def downgrade() -> None:
    op.drop_table('nation_intels')
    op.drop_table('military_formations')
    op.drop_table('military_production_queues')
