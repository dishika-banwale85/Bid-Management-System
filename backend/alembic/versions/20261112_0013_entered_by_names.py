"""Add optional entered-by names for audit visibility.

Revision ID: 20261112_0013
Revises: 20261103_0012
"""
from alembic import op
import sqlalchemy as sa

revision = "20261112_0013"
down_revision = "20261103_0012"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("audit_logs", sa.Column("entered_by", sa.String(length=80), nullable=True))
    op.add_column("bids", sa.Column("created_by_name", sa.String(length=80), nullable=True))
    op.add_column("bids", sa.Column("updated_by_name", sa.String(length=80), nullable=True))
    op.add_column("bids", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("compliance_requests", sa.Column("created_by_name", sa.String(length=80), nullable=True))
    op.add_column("compliance_requests", sa.Column("updated_by_name", sa.String(length=80), nullable=True))


def downgrade():
    op.drop_column("compliance_requests", "updated_by_name")
    op.drop_column("compliance_requests", "created_by_name")
    op.drop_column("bids", "updated_at")
    op.drop_column("bids", "updated_by_name")
    op.drop_column("bids", "created_by_name")
    op.drop_column("audit_logs", "entered_by")
