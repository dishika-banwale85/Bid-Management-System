"""Preserve previous request statuses and normalize submitted requests."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20261103_0012"
down_revision = "20261102_0011"
branch_labels = None
depends_on = None


def _has_column(table, name):
    return any(c["name"] == name for c in inspect(op.get_bind()).get_columns(table))


def upgrade():
    if not _has_column("compliance_requests", "legacy_status"):
        op.add_column("compliance_requests", sa.Column("legacy_status", sa.String(length=20), nullable=True))
    op.execute(
        "UPDATE compliance_requests SET legacy_status = status "
        "WHERE legacy_status IS NULL AND status <> 'DRAFT'"
    )
    op.execute(
        "UPDATE compliance_requests SET status = 'SUBMITTED' "
        "WHERE status <> 'DRAFT'"
    )


def downgrade():
    op.execute(
        "UPDATE compliance_requests SET status = legacy_status "
        "WHERE legacy_status IS NOT NULL"
    )
    op.drop_column("compliance_requests", "legacy_status")
