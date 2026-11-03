"""Store bid-specific not-applicable checklist selections."""
from alembic import op
import sqlalchemy as sa

revision = "20261102_0009"
down_revision = "20261102_0008"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "bid_checklist_na",
        sa.Column("bid_id", sa.Integer(), sa.ForeignKey("bids.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("request_type", sa.String(length=40), primary_key=True),
        sa.Column("marked_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("marked_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_bid_checklist_na_request_type", "bid_checklist_na", ["request_type"])
    op.create_index("ix_bid_checklist_na_marked_by", "bid_checklist_na", ["marked_by"])


def downgrade():
    op.drop_index("ix_bid_checklist_na_marked_by", table_name="bid_checklist_na")
    op.drop_index("ix_bid_checklist_na_request_type", table_name="bid_checklist_na")
    op.drop_table("bid_checklist_na")
