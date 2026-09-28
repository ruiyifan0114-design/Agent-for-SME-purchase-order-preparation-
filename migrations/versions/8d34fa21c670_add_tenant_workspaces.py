"""add tenant workspaces and memberships

Revision ID: 8d34fa21c670
Revises: 7b21e9c46f30
"""

from datetime import datetime, timezone
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "8d34fa21c670"
down_revision: Union[str, None] = "7b21e9c46f30"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LEGACY_ORG = "00000000-0000-0000-0000-000000000001"
LEGACY_WORKSPACE = "00000000-0000-0000-0000-000000000002"


def upgrade() -> None:
    op.create_table(
        "organization",
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(36), primary_key=True),
    )
    op.create_table(
        "workspace",
        sa.Column("org_id", sa.String(36), sa.ForeignKey("organization.id"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("business_entity", sa.String(200), nullable=False),
        sa.Column("warehouse", sa.String(100), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("finance_threshold", sa.Numeric(18, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(36), primary_key=True),
    )
    op.create_index("ix_workspace_org_id", "workspace", ["org_id"])
    op.create_table(
        "workspace_membership",
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspace.id"), nullable=False),
        sa.Column("user_id", sa.String(100), nullable=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("role", sa.String(30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(36), primary_key=True),
        sa.CheckConstraint("role IN ('owner','procurement','purchasing','finance','viewer')"),
        sa.UniqueConstraint("workspace_id", "email"),
        sa.UniqueConstraint("workspace_id", "user_id"),
    )
    op.create_index("ix_workspace_membership_workspace_id", "workspace_membership", ["workspace_id"])
    op.create_index("ix_workspace_membership_user_id", "workspace_membership", ["user_id"])

    now = datetime.now(timezone.utc)
    organization = sa.table("organization", sa.column("id"), sa.column("name"), sa.column("created_at"))
    workspace = sa.table(
        "workspace", sa.column("id"), sa.column("org_id"), sa.column("name"),
        sa.column("business_entity"), sa.column("warehouse"), sa.column("currency"),
        sa.column("finance_threshold"), sa.column("created_at"),
    )
    op.bulk_insert(organization, [{"id": LEGACY_ORG, "name": "Synthetic Office Co.", "created_at": now}])
    op.bulk_insert(workspace, [{
        "id": LEGACY_WORKSPACE, "org_id": LEGACY_ORG, "name": "Demo workspace",
        "business_entity": "Synthetic Office Co.", "warehouse": "Main warehouse",
        "currency": "SGD", "finance_threshold": 5000, "created_at": now,
    }])

    with op.batch_alter_table("import_batch") as batch:
        batch.add_column(sa.Column(
            "workspace_id", sa.String(36), nullable=False, server_default=LEGACY_WORKSPACE
        ))
        batch.create_foreign_key("fk_import_batch_workspace", "workspace", ["workspace_id"], ["id"])
        batch.create_index("ix_import_batch_workspace_id", ["workspace_id"])
        batch.alter_column("workspace_id", server_default=None)
    with op.batch_alter_table("tool_execution_log") as batch:
        batch.add_column(sa.Column(
            "workspace_id", sa.String(36), nullable=False, server_default=LEGACY_WORKSPACE
        ))
        batch.create_foreign_key(
            "fk_tool_execution_log_workspace", "workspace", ["workspace_id"], ["id"]
        )
        batch.create_index("ix_tool_execution_log_workspace_id", ["workspace_id"])
        batch.alter_column("workspace_id", server_default=None)

    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            """
            DO $$ DECLARE api_role text; BEGIN
              FOR api_role IN SELECT rolname FROM pg_roles WHERE rolname IN ('anon', 'authenticated') LOOP
                EXECUTE format('REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM %I', api_role);
                EXECUTE format('REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM %I', api_role);
              END LOOP;
            END $$;
            """
        )


def downgrade() -> None:
    with op.batch_alter_table("tool_execution_log") as batch:
        batch.drop_index("ix_tool_execution_log_workspace_id")
        batch.drop_constraint("fk_tool_execution_log_workspace", type_="foreignkey")
        batch.drop_column("workspace_id")
    with op.batch_alter_table("import_batch") as batch:
        batch.drop_index("ix_import_batch_workspace_id")
        batch.drop_constraint("fk_import_batch_workspace", type_="foreignkey")
        batch.drop_column("workspace_id")
    op.drop_index("ix_workspace_membership_user_id", table_name="workspace_membership")
    op.drop_index("ix_workspace_membership_workspace_id", table_name="workspace_membership")
    op.drop_table("workspace_membership")
    op.drop_index("ix_workspace_org_id", table_name="workspace")
    op.drop_table("workspace")
    op.drop_table("organization")
