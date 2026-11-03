"""Create or upgrade the Phase 1 and Phase 2 BidEase tables."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from app.db import Base
from app import models  # noqa
revision="20261022_0001"
down_revision=None
branch_labels=None
depends_on=None
def upgrade():
    bind=op.get_bind();inspector=inspect(bind);tables=set(inspector.get_table_names())
    def columns(table):return {c["name"] for c in inspect(bind).get_columns(table)} if table in set(inspect(bind).get_table_names()) else set()
    # Preserve databases created by the Phase 1 SQLAlchemy MVP.
    if "users" in tables and "is_active" not in columns("users"):
        op.add_column("users",sa.Column("is_active",sa.Boolean(),nullable=False,server_default=sa.true()))
        if "active" in columns("users"):op.execute("UPDATE users SET is_active = active")
    if "users" in tables and "active" in columns("users"):
        op.drop_column("users","active")
    if "roles" in tables:
        op.execute("UPDATE roles SET name='BID_TEAM' WHERE name='Bid Team Member'")
        op.execute("UPDATE roles SET name='APPROVER' WHERE name='Approver'")
        op.execute("UPDATE roles SET name='OPERATIONS' WHERE name='Operations'")
        op.execute("UPDATE roles SET name='ADMIN' WHERE name='Compliance Admin'")
    if "compliance_requests" in tables:
        if "created_by" not in columns("compliance_requests"):
            op.add_column("compliance_requests",sa.Column("created_by",sa.Integer(),sa.ForeignKey("users.id"),nullable=True))
            if "creator_id" in columns("compliance_requests"):op.execute("UPDATE compliance_requests SET created_by=creator_id")
        if "creator_id" in columns("compliance_requests"):
            for fk in inspect(bind).get_foreign_keys("compliance_requests"):
                if "creator_id" in fk.get("constrained_columns",[]) and fk.get("name"):op.drop_constraint(fk["name"],"compliance_requests",type_="foreignkey")
            op.drop_column("compliance_requests","creator_id")
        if "status" in columns("compliance_requests"):
            op.execute("UPDATE compliance_requests SET status='DRAFT' WHERE lower(status)='draft'")
            op.execute("UPDATE compliance_requests SET status='SUBMITTED' WHERE lower(status)='submitted'")
            op.execute("UPDATE compliance_requests SET status='IN_APPROVAL' WHERE lower(status) IN ('in approval','in_approval')")
            op.execute("UPDATE compliance_requests SET status='REJECTED' WHERE lower(status)='rejected'")
            op.execute("UPDATE compliance_requests SET status='COMPLETED' WHERE lower(status) IN ('approved','completed')")
        op.alter_column("compliance_requests","created_by",nullable=False)
    if "audit_logs" in tables:
        existing=columns("audit_logs")
        if "user_id" not in existing:
            op.add_column("audit_logs",sa.Column("user_id",sa.Integer(),sa.ForeignKey("users.id"),nullable=True))
            if "actor_id" in existing:op.execute("UPDATE audit_logs SET user_id=actor_id")
        if "actor_id" in columns("audit_logs"):
            for fk in inspect(bind).get_foreign_keys("audit_logs"):
                if "actor_id" in fk.get("constrained_columns",[]) and fk.get("name"):op.drop_constraint(fk["name"],"audit_logs",type_="foreignkey")
            op.drop_column("audit_logs","actor_id")
        if "request_id" not in existing:op.add_column("audit_logs",sa.Column("request_id",sa.Integer(),sa.ForeignKey("compliance_requests.id",ondelete="SET NULL"),nullable=True))
        if "old_status" not in existing:op.add_column("audit_logs",sa.Column("old_status",sa.String(length=30),nullable=True))
        if "new_status" not in existing:op.add_column("audit_logs",sa.Column("new_status",sa.String(length=30),nullable=True))
        if "entity_type" in existing:op.execute("UPDATE audit_logs SET request_id=entity_id WHERE entity_type='ComplianceRequest'")
        if "user_id" in columns("audit_logs"):op.alter_column("audit_logs","user_id",nullable=False)
    if "contacts" in tables:
        existing=columns("contacts")
        if "contact_type" not in existing:op.add_column("contacts",sa.Column("contact_type",sa.String(length=30),nullable=False,server_default="PRIMARY"))
        if "is_active" not in existing:op.add_column("contacts",sa.Column("is_active",sa.Boolean(),nullable=False,server_default=sa.true()))
    Base.metadata.create_all(bind=bind)
    for table in Base.metadata.tables.values():
        for index in table.indexes:index.create(bind=bind,checkfirst=True)
def downgrade():
    bind=op.get_bind();tables=set(inspect(bind).get_table_names())
    for name in ("notifications","email_logs","request_steps","workflow_steps","workflow_templates"):
        if name in tables:op.drop_table(name)
    if "compliance_requests" in tables:
        op.execute("UPDATE compliance_requests SET status='Draft' WHERE status='DRAFT'")
        op.execute("UPDATE compliance_requests SET status='Submitted' WHERE status='SUBMITTED'")
        op.execute("UPDATE compliance_requests SET status='In Approval' WHERE status='IN_APPROVAL'")
        op.execute("UPDATE compliance_requests SET status='Rejected' WHERE status='REJECTED'")
        op.execute("UPDATE compliance_requests SET status='Approved' WHERE status='COMPLETED'")
        cols={c["name"] for c in inspect(bind).get_columns("compliance_requests")}
        if "created_by" in cols and "creator_id" not in cols:
            op.add_column("compliance_requests",sa.Column("creator_id",sa.Integer(),nullable=True));op.execute("UPDATE compliance_requests SET creator_id=created_by");op.alter_column("compliance_requests","creator_id",nullable=False)
        if "created_by" in cols:op.drop_column("compliance_requests","created_by")
    if "audit_logs" in tables:
        cols={c["name"] for c in inspect(bind).get_columns("audit_logs")}
        if "user_id" in cols and "actor_id" not in cols:
            op.add_column("audit_logs",sa.Column("actor_id",sa.Integer(),nullable=True));op.execute("UPDATE audit_logs SET actor_id=user_id");op.alter_column("audit_logs","actor_id",nullable=False)
        for column in ("user_id","request_id","old_status","new_status"):
            if column in {c["name"] for c in inspect(bind).get_columns("audit_logs")}:op.drop_column("audit_logs",column)
    if "users" in tables:
        cols={c["name"] for c in inspect(bind).get_columns("users")}
        if "is_active" in cols and "active" not in cols:
            op.add_column("users",sa.Column("active",sa.Boolean(),nullable=False,server_default=sa.true()));op.execute("UPDATE users SET active=is_active")
        if "is_active" in {c["name"] for c in inspect(bind).get_columns("users")}:op.drop_column("users","is_active")
    if "roles" in tables:
        op.execute("UPDATE roles SET name='Bid Team Member' WHERE name='BID_TEAM'")
        op.execute("UPDATE roles SET name='Approver' WHERE name='APPROVER'")
        op.execute("UPDATE roles SET name='Operations' WHERE name='OPERATIONS'")
        op.execute("UPDATE roles SET name='Compliance Admin' WHERE name='ADMIN'")
