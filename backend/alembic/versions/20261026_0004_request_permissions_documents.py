"""Add explicit document types for request uploads."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20261026_0004"
down_revision = "20261026_0003"
branch_labels = None
depends_on = None


def upgrade():
    columns={c["name"] for c in inspect(op.get_bind()).get_columns("documents")}
    if "document_type" not in columns:
        op.add_column("documents",sa.Column("document_type",sa.String(length=60),nullable=False,server_default="OTHER"))
        op.create_index("ix_documents_document_type","documents",["document_type"])
        op.execute("UPDATE documents SET document_type = category WHERE category IN ('generated_challan','rfp','ep_approval','bg_copy','rfp_format','financial_documents','signed_declaration','hr_certificate')")
        op.alter_column("documents","document_type",server_default=None)


def downgrade():
    columns={c["name"] for c in inspect(op.get_bind()).get_columns("documents")}
    if "document_type" in columns:
        op.drop_index("ix_documents_document_type",table_name="documents")
        op.drop_column("documents","document_type")
