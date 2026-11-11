"""Preserve previous request statuses and normalize submitted requests.

Revision ID: 20261103_0012
Revises: 20261102_0011
"""
from alembic import op
import sqlalchemy as sa

revision = "20261103_0012"
down_revision = "20261102_0011"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("compliance_requests", sa.Column("legacy_status", sa.String(length=20), nullable=True))
    op.execute("UPDATE compliance_requests SET legacy_status = status")
    op.execute("UPDATE compliance_requests SET status = 'SUBMITTED' WHERE status <> 'DRAFT'")


def downgrade():
    op.drop_column("compliance_requests", "legacy_status")
