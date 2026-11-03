"""Add Phase 3 refund tracking and reminder deduplication."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20261025_0002"
down_revision = "20261022_0001"
branch_labels = None
depends_on = None

def upgrade():
    bind = op.get_bind()
    if "refund_received_at" not in {c["name"] for c in inspect(bind).get_columns("compliance_requests")}:
        op.add_column("compliance_requests", sa.Column("refund_received_at", sa.DateTime(timezone=True), nullable=True))
        op.create_index("ix_compliance_requests_refund_received_at", "compliance_requests", ["refund_received_at"])
    if "reminders_sent" not in inspect(bind).get_table_names():
        op.create_table("reminders_sent",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("request_id", sa.Integer(), sa.ForeignKey("compliance_requests.id", ondelete="CASCADE"), nullable=False),
            sa.Column("reminder_key", sa.String(120), nullable=False),
            sa.Column("sent_on", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("request_id", "reminder_key", name="uq_reminders_sent_request_key"))
        op.create_index("ix_reminders_sent_request_id", "reminders_sent", ["request_id"])

def downgrade():
    op.drop_index("ix_reminders_sent_request_id", table_name="reminders_sent")
    op.drop_table("reminders_sent")
    op.drop_index("ix_compliance_requests_refund_received_at", table_name="compliance_requests")
    op.drop_column("compliance_requests", "refund_received_at")
