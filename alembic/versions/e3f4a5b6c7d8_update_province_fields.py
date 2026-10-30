"""update_province_fields

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
Create Date: 2026-10-30 12:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = 'e3f4a5b6c7d8'
down_revision: Union[str, Sequence[str], None] = 'd2e3f4a5b6c7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('provinces') as batch_op:
        batch_op.add_column(sa.Column('code', sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column('country', sa.String(length=100), nullable=True, server_default='Unknown'))
        batch_op.add_column(sa.Column('country_code', sa.String(length=10), nullable=True, server_default='XX'))
        batch_op.add_column(sa.Column('display_name', sa.String(length=150), nullable=True, server_default=''))
        batch_op.add_column(sa.Column('search_name', sa.String(length=150), nullable=True, server_default=''))
        batch_op.add_column(sa.Column('aliases', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('climate', sa.String(length=50), nullable=True, server_default='temperate'))
        batch_op.add_column(sa.Column('deposits', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('population_capacity', sa.Integer(), nullable=True, server_default='100000'))
        batch_op.add_column(sa.Column('centroid_coords', sa.JSON(), nullable=True))
        batch_op.create_index('ix_provinces_code', ['code'], unique=True)
        batch_op.create_index('ix_provinces_display_name', ['display_name'], unique=False)
        batch_op.create_index('ix_provinces_search_name', ['search_name'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('provinces') as batch_op:
        batch_op.drop_index('ix_provinces_search_name')
        batch_op.drop_index('ix_provinces_display_name')
        batch_op.drop_index('ix_provinces_code')
        batch_op.drop_column('centroid_coords')
        batch_op.drop_column('population_capacity')
        batch_op.drop_column('deposits')
        batch_op.drop_column('climate')
        batch_op.drop_column('aliases')
        batch_op.drop_column('search_name')
        batch_op.drop_column('display_name')
        batch_op.drop_column('country_code')
        batch_op.drop_column('country')
        batch_op.drop_column('code')
