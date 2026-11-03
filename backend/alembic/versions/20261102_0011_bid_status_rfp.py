"""Add bid status and one RFP document per bid."""
from alembic import op
import sqlalchemy as sa

revision = "20261102_0011"
down_revision = "20261102_0010"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("bids", sa.Column("bid_status", sa.String(length=20), nullable=True, server_default="NOT_SUBMITTED"))
    op.execute("UPDATE bids SET bid_status = 'NOT_SUBMITTED' WHERE bid_status IS NULL")
    op.alter_column("bids", "bid_status", nullable=False, server_default="NOT_SUBMITTED")
    op.create_check_constraint("bid_status_values", "bids", "bid_status IN ('SUBMITTED','NOT_SUBMITTED','WIN','WITHDRAW','LOSE')")
    op.create_index("ix_bids_bid_status", "bids", ["bid_status"])
    op.create_table(
        "bid_documents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("bid_id", sa.Integer(), sa.ForeignKey("bids.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("document_type", sa.String(length=20), nullable=False, server_default="RFP"),
        sa.Column("original_name", sa.String(length=255), nullable=False),
        sa.Column("stored_name", sa.String(length=255), nullable=False, unique=True),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("content_type", sa.String(length=120), nullable=False),
        sa.Column("uploaded_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_bid_documents_bid_id", "bid_documents", ["bid_id"])
    op.create_index("ix_bid_documents_uploaded_by", "bid_documents", ["uploaded_by"])
    op.create_index("ix_bid_documents_uploaded_at", "bid_documents", ["uploaded_at"])


def downgrade():
    op.drop_index("ix_bid_documents_uploaded_at", table_name="bid_documents")
    op.drop_index("ix_bid_documents_uploaded_by", table_name="bid_documents")
    op.drop_index("ix_bid_documents_bid_id", table_name="bid_documents")
    op.drop_table("bid_documents")
    op.drop_index("ix_bids_bid_status", table_name="bids")
    op.drop_constraint("bid_status_values", "bids", type_="check")
    op.drop_column("bids", "bid_status")
