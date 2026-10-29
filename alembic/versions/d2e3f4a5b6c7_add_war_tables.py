"""add_war_tables

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
Create Date: 2026-10-30 10:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = 'd2e3f4a5b6c7'
down_revision: Union[str, Sequence[str], None] = 'c1d2e3f4a5b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'wars',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('attacker_id', sa.Integer(), nullable=False),
        sa.Column('defender_id', sa.Integer(), nullable=False),
        sa.Column('casus_belli', sa.String(length=50), nullable=False, server_default='none'),
        sa.Column('status', sa.String(length=30), nullable=False, server_default='active'),
        sa.Column('attacker_ap', sa.Integer(), nullable=False, server_default='12'),
        sa.Column('defender_ap', sa.Integer(), nullable=False, server_default='12'),
        sa.Column('attacker_fatigue', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('defender_fatigue', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('weather', sa.String(length=30), nullable=False, server_default='clear'),
        sa.Column('season', sa.String(length=30), nullable=False, server_default='spring'),
        sa.Column('created_at_turn', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('ended_at_turn', sa.Integer(), nullable=True),
        sa.Column('beige_until_turn', sa.Integer(), nullable=True),
        sa.Column('ceasefire_offered_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['attacker_id'], ['nations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['defender_id'], ['nations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_wars_attacker_id'), 'wars', ['attacker_id'], unique=False)
    op.create_index(op.f('ix_wars_defender_id'), 'wars', ['defender_id'], unique=False)
    op.create_index(op.f('ix_wars_status'), 'wars', ['status'], unique=False)

    op.create_table(
        'war_logs',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('war_id', sa.Integer(), nullable=False),
        sa.Column('turn_number', sa.Integer(), nullable=False),
        sa.Column('action_type', sa.String(length=50), nullable=False),
        sa.Column('attacker_id', sa.Integer(), nullable=False),
        sa.Column('defender_id', sa.Integer(), nullable=False),
        sa.Column('province_id', sa.Integer(), nullable=True),
        sa.Column('victory_tier', sa.String(length=50), nullable=False),
        sa.Column('attacker_score', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('defender_score', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('roll_diff', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('casualties', sa.JSON(), nullable=False),
        sa.Column('loot_resources', sa.JSON(), nullable=False),
        sa.Column('modifiers_applied', sa.JSON(), nullable=False),
        sa.Column('summary', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['war_id'], ['wars.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_war_logs_war_id'), 'war_logs', ['war_id'], unique=False)


def downgrade() -> None:
    op.drop_table('war_logs')
    op.drop_table('wars')
