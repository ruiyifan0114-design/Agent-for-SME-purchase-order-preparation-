"""production foundation: rules, provenance, jobs and observability

Revision ID: d7e5a9c2f410
Revises: c1a8e2f4b6d0
"""
from datetime import datetime, timezone
from uuid import NAMESPACE_URL, uuid5

from alembic import op
import sqlalchemy as sa

revision = "d7e5a9c2f410"
down_revision = "c1a8e2f4b6d0"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "rule_set",
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspace.id"), nullable=False),
        sa.Column("rule_version", sa.Integer(), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rules", sa.JSON(), nullable=False),
        sa.Column("approval_policy", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(36), primary_key=True),
        sa.CheckConstraint("rule_version > 0"),
        sa.UniqueConstraint("workspace_id", "rule_version"),
    )
    op.create_index("ix_rule_set_workspace_id", "rule_set", ["workspace_id"])
    op.create_index("ix_rule_set_effective_from", "rule_set", ["effective_from"])
    op.create_index("ix_rule_set_effective_to", "rule_set", ["effective_to"])

    with op.batch_alter_table("import_batch") as batch:
        batch.add_column(sa.Column("idempotency_key", sa.String(128), nullable=True))
        batch.add_column(sa.Column("source_system", sa.String(80), nullable=False, server_default="manual"))
        batch.add_column(sa.Column("external_id", sa.String(200), nullable=True))
        batch.add_column(sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("source_metadata", sa.JSON(), nullable=False, server_default="{}"))
        batch.create_unique_constraint("uq_import_workspace_idempotency", ["workspace_id", "idempotency_key"])
        batch.create_unique_constraint("uq_import_workspace_external", ["workspace_id", "source_system", "external_id"])

    source_tables = ("sku_master", "supplier_master", "supplier_sku", "inventory_snapshot", "demand", "open_po")
    for table in source_tables:
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("source_system", sa.String(80), nullable=False, server_default="manual"))
            batch.add_column(sa.Column("external_id", sa.String(200), nullable=True))
            batch.add_column(sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True))
            batch.add_column(sa.Column("source_metadata", sa.JSON(), nullable=False, server_default="{}"))
            batch.create_index(f"ix_{table}_external_id", ["external_id"])

    with op.batch_alter_table("procurement_run") as batch:
        batch.add_column(sa.Column("idempotency_key", sa.String(128), nullable=True))
        batch.add_column(sa.Column("rule_set_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("rule_version", sa.Integer(), nullable=False, server_default="1"))
        batch.add_column(sa.Column("rules_snapshot", sa.JSON(), nullable=False, server_default="{}"))
        batch.add_column(sa.Column("approval_policy_snapshot", sa.JSON(), nullable=False, server_default="{}"))
        batch.create_foreign_key("fk_procurement_run_rule_set", "rule_set", ["rule_set_id"], ["id"])
        batch.create_index("ix_procurement_run_rule_set_id", ["rule_set_id"])
        batch.create_unique_constraint("uq_run_batch_idempotency", ["batch_id", "idempotency_key"])

    with op.batch_alter_table("tool_execution_log") as batch:
        batch.add_column(sa.Column("user_id", sa.String(100), nullable=False, server_default=""))
        batch.add_column(sa.Column("correlation_id", sa.String(64), nullable=False, server_default=""))
        batch.add_column(sa.Column("duration_ms", sa.Integer(), nullable=True))

    op.create_table(
        "job_record",
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspace.id"), nullable=False),
        sa.Column("job_type", sa.String(80), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("correlation_id", sa.String(64), nullable=False),
        sa.Column("created_by", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(36), primary_key=True),
        sa.UniqueConstraint("workspace_id", "idempotency_key"),
    )
    for column in ("workspace_id", "job_type", "status", "available_at"):
        op.create_index(f"ix_job_record_{column}", "job_record", [column])

    # Existing runs retain their scalar policy columns; snapshots make that policy explicit.
    bind = op.get_bind()
    workspaces = bind.execute(sa.text("SELECT id, currency, finance_threshold FROM workspace")).mappings()
    now = datetime.now(timezone.utc)
    for workspace in workspaces:
        rule_id = str(uuid5(NAMESPACE_URL, f"supplydesk:legacy-rule:{workspace['id']}"))
        insert_rule = sa.text(
            "INSERT INTO rule_set (id, workspace_id, rule_version, effective_from, effective_to, rules, "
            "approval_policy, created_by, created_at) VALUES (:id,:workspace,1,:effective,NULL,:rules,:approval,:actor,:created)"
        ).bindparams(sa.bindparam("rules", type_=sa.JSON()), sa.bindparam("approval", type_=sa.JSON()))
        approval = {"currency": workspace["currency"], "finance_threshold": str(workspace["finance_threshold"])}
        bind.execute(insert_rule, {"id": rule_id, "workspace": workspace["id"],
            "effective": datetime(1970, 1, 1, tzinfo=timezone.utc),
            "rules": {"replenishment_policy": "BELOW_SAFETY_TO_TARGET", "rounding_policy": "MOQ_PACK_CEILING"},
            "approval": approval,
            "actor": "migration", "created": now})
        runs = bind.execute(sa.text(
            "SELECT procurement_run.id, batch_id, as_of, horizon, currency, warehouse, inventory_max_age_days, "
            "commercial_max_age_days FROM procurement_run JOIN import_batch ON import_batch.id=procurement_run.batch_id "
            "WHERE import_batch.workspace_id=:workspace"
        ), {"workspace": workspace["id"]}).mappings()
        for run in runs:
            policy = {"run_policy": {
                "batch_id": run["batch_id"], "as_of": str(run["as_of"]), "horizon": run["horizon"],
                "currency": run["currency"], "warehouse": run["warehouse"],
                "inventory_max_age_days": run["inventory_max_age_days"],
                "commercial_max_age_days": run["commercial_max_age_days"],
            }}
            update_run = sa.text(
                "UPDATE procurement_run SET rule_set_id=:rule, rule_version=1, rules_snapshot=:rules, "
                "approval_policy_snapshot=:approval WHERE id=:id"
            ).bindparams(sa.bindparam("rules", type_=sa.JSON()), sa.bindparam("approval", type_=sa.JSON()))
            bind.execute(update_run, {"rule": rule_id, "rules": policy, "approval": approval,
                "id": run["id"]})
    with op.batch_alter_table("procurement_run") as batch:
        batch.alter_column("rule_set_id", existing_type=sa.String(36), nullable=False)


def downgrade():
    for column in ("available_at", "status", "job_type", "workspace_id"):
        op.drop_index(f"ix_job_record_{column}", table_name="job_record")
    op.drop_table("job_record")
    with op.batch_alter_table("tool_execution_log") as batch:
        batch.drop_column("duration_ms")
        batch.drop_column("correlation_id")
        batch.drop_column("user_id")
    with op.batch_alter_table("procurement_run") as batch:
        batch.drop_constraint("uq_run_batch_idempotency", type_="unique")
        batch.drop_index("ix_procurement_run_rule_set_id")
        batch.drop_constraint("fk_procurement_run_rule_set", type_="foreignkey")
        for column in ("approval_policy_snapshot", "rules_snapshot", "rule_version", "rule_set_id", "idempotency_key"):
            batch.drop_column(column)
    for table in ("sku_master", "supplier_master", "supplier_sku", "inventory_snapshot", "demand", "open_po"):
        with op.batch_alter_table(table) as batch:
            batch.drop_index(f"ix_{table}_external_id")
            for column in ("source_metadata", "synced_at", "external_id", "source_system"):
                batch.drop_column(column)
    with op.batch_alter_table("import_batch") as batch:
        batch.drop_constraint("uq_import_workspace_external", type_="unique")
        batch.drop_constraint("uq_import_workspace_idempotency", type_="unique")
        for column in ("source_metadata", "synced_at", "external_id", "source_system", "idempotency_key"):
            batch.drop_column(column)
    op.drop_index("ix_rule_set_effective_to", table_name="rule_set")
    op.drop_index("ix_rule_set_effective_from", table_name="rule_set")
    op.drop_index("ix_rule_set_workspace_id", table_name="rule_set")
    op.drop_table("rule_set")
