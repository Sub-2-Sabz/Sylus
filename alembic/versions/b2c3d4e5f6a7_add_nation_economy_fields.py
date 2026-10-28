"""add nation economy buildings and market index fields

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2025-02-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add new columns to nations
    with op.batch_alter_table('nations', schema=None) as batch_op:
        batch_op.add_column(sa.Column('leader_name', sa.String(length=100), nullable=False, server_default='Leader'))
        batch_op.add_column(sa.Column('flag_url', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('government_type', sa.String(length=50), nullable=False, server_default='republic'))
        batch_op.add_column(sa.Column('ideology', sa.String(length=50), nullable=False, server_default='centrism'))
        batch_op.add_column(sa.Column('custom_leader_title', sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column('custom_govt_title', sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column('tax_rate', sa.Float(), nullable=False, server_default='0.15'))
        batch_op.add_column(sa.Column('happiness', sa.Float(), nullable=False, server_default='0.80'))
        batch_op.add_column(sa.Column('population', sa.Integer(), nullable=False, server_default='10000'))
        batch_op.add_column(sa.Column('score', sa.Float(), nullable=False, server_default='100.0'))
        batch_op.add_column(sa.Column('active_policies', sa.JSON(), nullable=False, server_default='{}'))
        batch_op.add_column(sa.Column('policy_cooldowns', sa.JSON(), nullable=False, server_default='{}'))

    # Add new columns to provinces
    with op.batch_alter_table('provinces', schema=None) as batch_op:
        batch_op.add_column(sa.Column('population', sa.Integer(), nullable=False, server_default='10000'))
        batch_op.add_column(sa.Column('infrastructure', sa.Integer(), nullable=False, server_default='1'))
        batch_op.add_column(sa.Column('slot_cap', sa.Integer(), nullable=False, server_default='5'))

    # Create buildings table
    op.create_table(
        'buildings',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('province_id', sa.Integer(), nullable=False),
        sa.Column('nation_id', sa.Integer(), nullable=False),
        sa.Column('building_type', sa.String(length=50), nullable=False),
        sa.Column('level', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('turns_remaining', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['nation_id'], ['nations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['province_id'], ['provinces.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_buildings_nation_id'), 'buildings', ['nation_id'], unique=False)
    op.create_index(op.f('ix_buildings_province_id'), 'buildings', ['province_id'], unique=False)

    # Create resource_market_index table
    op.create_table(
        'resource_market_index',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('resource_type', sa.String(length=50), nullable=False),
        sa.Column('current_price', sa.Float(), nullable=False),
        sa.Column('supply_turn', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('demand_turn', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_resource_market_index_resource_type'), 'resource_market_index', ['resource_type'], unique=True)


def downgrade() -> None:
    op.drop_index(op.f('ix_resource_market_index_resource_type'), table_name='resource_market_index')
    op.drop_table('resource_market_index')

    op.drop_index(op.f('ix_buildings_province_id'), table_name='buildings')
    op.drop_index(op.f('ix_buildings_nation_id'), table_name='buildings')
    op.drop_table('buildings')

    with op.batch_alter_table('provinces', schema=None) as batch_op:
        batch_op.drop_column('slot_cap')
        batch_op.drop_column('infrastructure')
        batch_op.drop_column('population')

    with op.batch_alter_table('nations', schema=None) as batch_op:
        batch_op.drop_column('policy_cooldowns')
        batch_op.drop_column('active_policies')
        batch_op.drop_column('score')
        batch_op.drop_column('population')
        batch_op.drop_column('happiness')
        batch_op.drop_column('tax_rate')
        batch_op.drop_column('custom_govt_title')
        batch_op.drop_column('custom_leader_title')
        batch_op.drop_column('ideology')
        batch_op.drop_column('government_type')
        batch_op.drop_column('flag_url')
        batch_op.drop_column('leader_name')
