"""Add reversible soft-delete fields for bids."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20261102_0010"
down_revision = "20261102_0009"
branch_labels = None
depends_on = None


def _has_column(table, name):
    return any(c["name"] == name for c in inspect(op.get_bind()).get_columns(table))


def _has_index(table, name):
    return any(ix["name"] == name for ix in inspect(op.get_bind()).get_indexes(table))


def upgrade():
    if not _has_column("bids", "deleted_at"):
        op.add_column("bids", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    if not _has_column("bids", "deleted_by"):
        op.add_column("bids", sa.Column("deleted_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True))
    if not _has_column("bids", "delete_reason"):
        op.add_column("bids", sa.Column("delete_reason", sa.String(length=500), nullable=True))
    if not _has_index("bids", "ix_bids_deleted_at"):
        op.create_index("ix_bids_deleted_at", "bids", ["deleted_at"])


def downgrade():
    op.drop_index("ix_bids_deleted_at", table_name="bids")
    op.drop_column("bids", "delete_reason")
    op.drop_column("bids", "deleted_by")
    op.drop_column("bids", "deleted_at")
