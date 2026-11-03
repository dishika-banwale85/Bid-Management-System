"""Add reversible soft-delete fields for bids."""
from alembic import op
import sqlalchemy as sa

revision = "20261102_0010"
down_revision = "20261102_0009"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("bids", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("bids", sa.Column("deleted_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True))
    op.add_column("bids", sa.Column("delete_reason", sa.Text(), nullable=True))
    op.create_index("ix_bids_deleted_at", "bids", ["deleted_at"])
    op.create_index("ix_bids_deleted_by", "bids", ["deleted_by"])


def downgrade():
    op.drop_index("ix_bids_deleted_by", table_name="bids")
    op.drop_index("ix_bids_deleted_at", table_name="bids")
    op.drop_column("bids", "delete_reason")
    op.drop_column("bids", "deleted_by")
    op.drop_column("bids", "deleted_at")
