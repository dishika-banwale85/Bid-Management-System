"""Persist hashed, expiring CAPTCHA challenges."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20261102_0008"
down_revision = "20261101_0007"
branch_labels = None
depends_on = None


def _has_table(name):
    return inspect(op.get_bind()).has_table(name)


def _has_index(table, name):
    return any(ix["name"] == name for ix in inspect(op.get_bind()).get_indexes(table))


def upgrade():
    if not _has_table("captcha_challenges"):
        op.create_table(
            "captcha_challenges",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column("answer_hash", sa.String(length=64), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
    if not _has_index("captcha_challenges", "ix_captcha_challenges_expires_at"):
        op.create_index("ix_captcha_challenges_expires_at", "captcha_challenges", ["expires_at"])
    if not _has_index("captcha_challenges", "ix_captcha_challenges_used_at"):
        op.create_index("ix_captcha_challenges_used_at", "captcha_challenges", ["used_at"])


def downgrade():
    op.drop_index("ix_captcha_challenges_used_at", table_name="captcha_challenges")
    op.drop_index("ix_captcha_challenges_expires_at", table_name="captcha_challenges")
    op.drop_table("captcha_challenges")
