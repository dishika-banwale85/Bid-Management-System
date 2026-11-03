"""Add versioned workflow definitions and editable form display templates."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20261026_0003"
down_revision = "20261025_0002"
branch_labels = None
depends_on = None

def upgrade():
    bind=op.get_bind();inspector=inspect(bind)
    if "version" not in {c["name"] for c in inspector.get_columns("workflow_templates")}:
        op.add_column("workflow_templates",sa.Column("version",sa.Integer(),nullable=False,server_default="1"))
    step_cols={c["name"] for c in inspect(bind).get_columns("workflow_steps")}
    if "version" not in step_cols:
        op.add_column("workflow_steps",sa.Column("version",sa.Integer(),nullable=False,server_default="1"))
        op.create_index("ix_workflow_steps_version","workflow_steps",["version"])
    # Replace the old per-template ordering key so each immutable version can retain its own order.
    for constraint in inspect(bind).get_unique_constraints("workflow_steps"):
        if set(constraint.get("column_names") or [])=={"template_id","step_order"} and constraint.get("name"):
            op.drop_constraint(constraint["name"],"workflow_steps",type_="unique")
    if not any(set(c.get("column_names") or [])=={"template_id","version","step_order"} for c in inspect(bind).get_unique_constraints("workflow_steps")):
        op.create_unique_constraint("uq_workflow_steps_template_version_order","workflow_steps",["template_id","version","step_order"])
    if "form_templates" not in inspect(bind).get_table_names():
        op.create_table("form_templates",
            sa.Column("id",sa.Integer(),primary_key=True),
            sa.Column("request_type",sa.String(40),nullable=False,unique=True),
            sa.Column("display_name",sa.String(120),nullable=False),
            sa.Column("fields",sa.JSON(),nullable=False),
            sa.Column("required_documents",sa.JSON(),nullable=False),
            sa.Column("updated_by",sa.Integer(),sa.ForeignKey("users.id"),nullable=True),
            sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False))
        op.create_index("ix_form_templates_request_type","form_templates",["request_type"])

def downgrade():
    op.drop_index("ix_form_templates_request_type",table_name="form_templates")
    op.drop_table("form_templates")
    op.drop_constraint("uq_workflow_steps_template_version_order","workflow_steps",type_="unique")
    op.create_unique_constraint("uq_workflow_steps_template_order","workflow_steps",["template_id","step_order"])
    op.drop_index("ix_workflow_steps_version",table_name="workflow_steps")
    op.drop_column("workflow_steps","version")
    op.drop_column("workflow_templates","version")
