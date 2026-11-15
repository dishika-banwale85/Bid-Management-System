"""Add expanded RFP and client details to bids."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20261027_0005"
down_revision = "20261026_0004"
branch_labels = None
depends_on = None


def upgrade():
    inspector = inspect(op.get_bind())
    existing_columns = {
        column["name"] for column in inspector.get_columns("bids")
    }

    columns_to_add = [
        ("rfp_published_date", sa.Date(), True, None),
        ("project_title", sa.String(length=250), True, None),
        ("prebid_meeting_date", sa.Date(), True, None),
        ("prebid_query_deadline", sa.Date(), True, None),
        ("prebid_meeting_na", sa.Boolean(), False, sa.false()),
        ("prebid_query_na", sa.Boolean(), False, sa.false()),
        ("client_address", sa.String(length=500), True, None),
    ]

    for name, column_type, nullable, server_default in columns_to_add:
        if name not in existing_columns:
            op.add_column(
                "bids",
                sa.Column(
                    name,
                    column_type,
                    nullable=nullable,
                    server_default=server_default,
                ),
            )

def downgrade():
    op.drop_column("bids", "client_address")
    op.drop_column("bids", "prebid_query_na")
    op.drop_column("bids", "prebid_meeting_na")
    op.drop_column("bids", "prebid_query_deadline")
    op.drop_column("bids", "prebid_meeting_date")
    op.drop_column("bids", "project_title")
    op.drop_column("bids", "rfp_published_date")
