"""Add prototype mail contacts and additional workflow roles.

Existing contact rows and email log entries are retained. New profile fields are
nullable, and the recipient status column is widened for simulation outcomes.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20261027_0006"
down_revision = "20261027_0005"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    contact_columns = {column["name"] for column in inspector.get_columns("contacts")}
    if "designation" not in contact_columns:
        op.add_column("contacts", sa.Column("designation", sa.String(length=160), nullable=True))
    if "department" not in contact_columns:
        op.add_column("contacts", sa.Column("department", sa.String(length=160), nullable=True))
    if "email" in contact_columns:
        op.alter_column("contacts", "email", existing_type=sa.String(length=255), nullable=True)

    log_columns = {column["name"]: column for column in inspect(bind).get_columns("email_logs")}
    if "status" in log_columns and getattr(log_columns["status"]["type"], "length", None) != 32:
        op.alter_column("email_logs", "status", existing_type=sa.String(length=10), type_=sa.String(length=32), existing_nullable=False)

    # Role names are plain strings with a unique index; insert only missing rows.
    for role in ("SENIOR_MANAGER", "PACE_COORDINATOR", "DECLARATION_TEAM"):
        bind.execute(sa.text("INSERT INTO roles (name) VALUES (:name) ON CONFLICT (name) DO NOTHING"), {"name": role})


def downgrade():
    # Intentionally preserve contact details, simulated-mail history, and roles.
    # This project does not use destructive downgrades for user data.
    pass
