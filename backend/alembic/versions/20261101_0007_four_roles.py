"""Map legacy specialist roles into the consolidated Approver role.

Legacy role rows are retained to preserve foreign-key history. User and
workflow assignments move to one of the four supported roles.
"""
from alembic import op
import sqlalchemy as sa

revision = "20261101_0007"
down_revision = "20261027_0006"
branch_labels = None
depends_on = None

LEGACY_ROLES = (
    "FINANCE",
    "HR",
    "OPERATIONS",
    "RISK",
    "DECLARATION_TEAM",
    "SENIOR_MANAGER",
)


def upgrade():
    bind = op.get_bind()
    bind.execute(sa.text("INSERT INTO roles (name) VALUES ('APPROVER') ON CONFLICT (name) DO NOTHING"))
    legacy_roles = sa.bindparam("legacy", expanding=True)
    bind.execute(sa.text("UPDATE users SET role_id=(SELECT id FROM roles WHERE name='APPROVER') WHERE role_id IN (SELECT id FROM roles WHERE name IN :legacy)").bindparams(legacy_roles), {"legacy": LEGACY_ROLES})
    bind.execute(sa.text("UPDATE workflow_steps SET assigned_role='APPROVER' WHERE assigned_role IN :legacy").bindparams(legacy_roles), {"legacy": LEGACY_ROLES})


def downgrade():
    # Role consolidation is intentionally irreversible: assignments are kept
    # under APPROVER so no users or workflow steps are lost or made unusable.
    pass
