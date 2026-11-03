"""Add expanded RFP and client details to bids."""
from alembic import op
import sqlalchemy as sa

revision = "20261027_0005"
down_revision = "20261026_0004"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("bids", sa.Column("rfp_published_date", sa.Date(), nullable=True))
    op.add_column("bids", sa.Column("project_title", sa.String(length=250), nullable=True))
    op.add_column("bids", sa.Column("prebid_meeting_date", sa.Date(), nullable=True))
    op.add_column("bids", sa.Column("prebid_query_deadline", sa.Date(), nullable=True))
    op.add_column("bids", sa.Column("prebid_meeting_na", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("bids", sa.Column("prebid_query_na", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("bids", sa.Column("client_address", sa.String(length=500), nullable=True))


def downgrade():
    op.drop_column("bids", "client_address")
    op.drop_column("bids", "prebid_query_na")
    op.drop_column("bids", "prebid_meeting_na")
    op.drop_column("bids", "prebid_query_deadline")
    op.drop_column("bids", "prebid_meeting_date")
    op.drop_column("bids", "project_title")
    op.drop_column("bids", "rfp_published_date")
