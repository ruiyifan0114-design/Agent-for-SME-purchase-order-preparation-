"""advanced sourcing, receiving, matching and approval domain

Revision ID: e8f6b0d3a521
Revises: d7e5a9c2f410
"""
from alembic import op
import sqlalchemy as sa

revision = "e8f6b0d3a521"
down_revision = "d7e5a9c2f410"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("supplier_performance",
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspace.id"), nullable=False),
        sa.Column("supplier_id", sa.String(80), nullable=False), sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("on_time_rate", sa.Numeric(7, 6)), sa.Column("lead_time_variance_days", sa.Numeric(10, 4)),
        sa.Column("rejection_rate", sa.Numeric(7, 6)), sa.Column("historical_score", sa.Numeric(7, 6)),
        sa.Column("source_metadata", sa.JSON(), nullable=False), sa.Column("id", sa.String(36), primary_key=True),
        sa.UniqueConstraint("workspace_id", "supplier_id", "period_end"))
    op.create_index("ix_supplier_performance_workspace_id", "supplier_performance", ["workspace_id"])
    op.create_index("ix_supplier_performance_supplier_id", "supplier_performance", ["supplier_id"])
    op.create_table("commercial_agreement",
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspace.id"), nullable=False),
        sa.Column("supplier_id", sa.String(80), nullable=False), sa.Column("sku_id", sa.String(80), nullable=False),
        sa.Column("agreement_number", sa.String(100), nullable=False), sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date()), sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("terms", sa.JSON(), nullable=False), sa.Column("rule_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("id", sa.String(36), primary_key=True))
    for col in ("workspace_id", "supplier_id", "sku_id"):
        op.create_index(f"ix_commercial_agreement_{col}", "commercial_agreement", [col])
    op.create_table("sku_inventory_policy",
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspace.id"), nullable=False),
        sa.Column("sku_id", sa.String(80), nullable=False), sa.Column("policy_type", sa.String(30), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False), sa.Column("rule_version", sa.Integer(), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_to", sa.DateTime(timezone=True)), sa.Column("id", sa.String(36), primary_key=True),
        sa.UniqueConstraint("workspace_id", "sku_id", "rule_version"))
    op.create_index("ix_sku_inventory_policy_workspace_id", "sku_inventory_policy", ["workspace_id"])
    op.create_index("ix_sku_inventory_policy_sku_id", "sku_inventory_policy", ["sku_id"])
    op.create_table("sourcing_decision",
        sa.Column("result_id", sa.String(36), sa.ForeignKey("sku_check_result.id"), nullable=False),
        sa.Column("rule_version", sa.Integer(), nullable=False), sa.Column("trace", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(36), primary_key=True), sa.UniqueConstraint("result_id"))
    op.create_index("ix_sourcing_decision_result_id", "sourcing_decision", ["result_id"])
    old_unique = next((constraint["name"] for constraint in
        sa.inspect(op.get_bind()).get_unique_constraints("po_line")
        if constraint["column_names"] == ["result_id"]), None)
    with op.batch_alter_table("po_line", naming_convention={"uq": "uq_%(table_name)s_%(column_0_name)s"}, table_args=(
        sa.CheckConstraint("quantity > 0", name="ck_po_line_quantity_positive"),
        sa.CheckConstraint("unit_price > 0", name="ck_po_line_unit_price_positive"),
    )) as batch:
        batch.drop_constraint(old_unique or "uq_po_line_result_id", type_="unique")
        batch.create_unique_constraint("uq_po_line_result_draft", ["result_id", "draft_id"])
    with op.batch_alter_table("po_draft") as batch:
        batch.add_column(sa.Column("lifecycle_status", sa.String(30), nullable=False, server_default="DRAFT"))
        for name in ("cost_center", "project_code", "budget_code"):
            batch.add_column(sa.Column(name, sa.String(80)))
        for name in ("tax", "freight", "duty", "landed_cost"):
            batch.add_column(sa.Column(name, sa.Numeric(32, 2), nullable=False, server_default="0"))
        batch.add_column(sa.Column("base_currency", sa.String(3)))
        batch.add_column(sa.Column("exchange_rate", sa.Numeric(18, 8)))
        batch.add_column(sa.Column("exchange_rate_date", sa.Date()))
        batch.add_column(sa.Column("exchange_rate_source", sa.String(100)))
    with op.batch_alter_table("po_line", table_args=(
        sa.CheckConstraint("quantity > 0", name="ck_po_line_quantity_positive"),
        sa.CheckConstraint("unit_price > 0", name="ck_po_line_unit_price_positive"),
    )) as batch:
        batch.add_column(sa.Column("received_quantity", sa.BigInteger(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("returned_quantity", sa.BigInteger(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("open_quantity", sa.BigInteger(), nullable=False, server_default="0"))
    op.execute("UPDATE po_line SET open_quantity = quantity")
    op.create_table("budget",
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspace.id"), nullable=False),
        sa.Column("budget_code", sa.String(80), nullable=False), sa.Column("cost_center", sa.String(80)),
        sa.Column("project_code", sa.String(80)), sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("authorized_amount", sa.Numeric(32, 2), nullable=False),
        sa.Column("committed_amount", sa.Numeric(32, 2), nullable=False), sa.Column("id", sa.String(36), primary_key=True),
        sa.UniqueConstraint("workspace_id", "budget_code", "currency"))
    for col in ("workspace_id", "cost_center", "project_code"):
        op.create_index(f"ix_budget_{col}", "budget", [col])
    op.create_table("goods_receipt",
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspace.id"), nullable=False),
        sa.Column("draft_id", sa.String(36), sa.ForeignKey("po_draft.id"), nullable=False),
        sa.Column("external_id", sa.String(100), nullable=False), sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(30), nullable=False), sa.Column("source_metadata", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(200), nullable=False), sa.Column("id", sa.String(36), primary_key=True),
        sa.UniqueConstraint("workspace_id", "external_id"))
    op.create_index("ix_goods_receipt_workspace_id", "goods_receipt", ["workspace_id"])
    op.create_index("ix_goods_receipt_draft_id", "goods_receipt", ["draft_id"])
    op.create_table("goods_receipt_line",
        sa.Column("receipt_id", sa.String(36), sa.ForeignKey("goods_receipt.id"), nullable=False),
        sa.Column("po_line_id", sa.String(36), sa.ForeignKey("po_line.id"), nullable=False),
        sa.Column("sku_id", sa.String(80), nullable=False), sa.Column("quantity", sa.BigInteger(), nullable=False),
        sa.Column("rejected_quantity", sa.BigInteger(), nullable=False),
        sa.Column("returned_quantity", sa.BigInteger(), nullable=False), sa.Column("id", sa.String(36), primary_key=True))
    op.create_index("ix_goods_receipt_line_receipt_id", "goods_receipt_line", ["receipt_id"])
    op.create_index("ix_goods_receipt_line_po_line_id", "goods_receipt_line", ["po_line_id"])
    op.create_table("supplier_invoice",
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspace.id"), nullable=False),
        sa.Column("draft_id", sa.String(36), sa.ForeignKey("po_draft.id"), nullable=False),
        sa.Column("supplier_id", sa.String(80), nullable=False), sa.Column("invoice_number", sa.String(100), nullable=False),
        sa.Column("invoice_date", sa.Date(), nullable=False), sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("exchange_rate", sa.Numeric(18, 8), nullable=False), sa.Column("exchange_rate_date", sa.Date(), nullable=False),
        sa.Column("exchange_rate_source", sa.String(100), nullable=False), sa.Column("total", sa.Numeric(32, 2), nullable=False),
        sa.Column("status", sa.String(30), nullable=False), sa.Column("id", sa.String(36), primary_key=True),
        sa.UniqueConstraint("workspace_id", "supplier_id", "invoice_number"))
    op.create_index("ix_supplier_invoice_workspace_id", "supplier_invoice", ["workspace_id"])
    op.create_index("ix_supplier_invoice_draft_id", "supplier_invoice", ["draft_id"])
    op.create_table("supplier_invoice_line",
        sa.Column("invoice_id", sa.String(36), sa.ForeignKey("supplier_invoice.id"), nullable=False),
        sa.Column("po_line_id", sa.String(36), sa.ForeignKey("po_line.id"), nullable=False),
        sa.Column("sku_id", sa.String(80), nullable=False), sa.Column("quantity", sa.BigInteger(), nullable=False),
        sa.Column("unit_price", sa.Numeric(18, 4), nullable=False), sa.Column("amount", sa.Numeric(32, 2), nullable=False),
        sa.Column("id", sa.String(36), primary_key=True))
    op.create_index("ix_supplier_invoice_line_invoice_id", "supplier_invoice_line", ["invoice_id"])
    op.create_index("ix_supplier_invoice_line_po_line_id", "supplier_invoice_line", ["po_line_id"])
    op.create_table("match_result",
        sa.Column("invoice_id", sa.String(36), sa.ForeignKey("supplier_invoice.id"), nullable=False),
        sa.Column("po_line_id", sa.String(36), sa.ForeignKey("po_line.id"), nullable=False),
        sa.Column("status", sa.String(30), nullable=False), sa.Column("rule_version", sa.Integer(), nullable=False),
        sa.Column("trace", sa.JSON(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(36), primary_key=True))
    op.create_index("ix_match_result_invoice_id", "match_result", ["invoice_id"])
    op.create_index("ix_match_result_po_line_id", "match_result", ["po_line_id"])
    op.create_table("approval_matrix_rule",
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspace.id"), nullable=False),
        sa.Column("rule_version", sa.Integer(), nullable=False), sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("conditions", sa.JSON(), nullable=False), sa.Column("required_role", sa.String(50), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_to", sa.DateTime(timezone=True)), sa.Column("id", sa.String(36), primary_key=True))
    op.create_index("ix_approval_matrix_rule_workspace_id", "approval_matrix_rule", ["workspace_id"])
    op.create_table("approval_delegation",
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspace.id"), nullable=False),
        sa.Column("delegator_user_id", sa.String(100), nullable=False), sa.Column("delegator_role", sa.String(50), nullable=False),
        sa.Column("delegate_user_id", sa.String(100), nullable=False), sa.Column("delegate_role", sa.String(50), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False), sa.Column("valid_to", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False), sa.Column("created_by", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("id", sa.String(36), primary_key=True))
    for col in ("workspace_id", "delegator_user_id", "delegate_user_id"):
        op.create_index(f"ix_approval_delegation_{col}", "approval_delegation", [col])
    if op.get_bind().dialect.name == "postgresql":
        op.execute("""
        DO $$
        DECLARE api_role text;
        BEGIN
          FOR api_role IN SELECT rolname FROM pg_roles WHERE rolname IN ('anon', 'authenticated') LOOP
            EXECUTE format(
              'REVOKE ALL PRIVILEGES ON TABLE supplier_performance, commercial_agreement, '
              'sku_inventory_policy, sourcing_decision, budget, goods_receipt, goods_receipt_line, '
              'supplier_invoice, supplier_invoice_line, match_result, approval_matrix_rule, '
              'approval_delegation FROM %I', api_role
            );
          END LOOP;
        END $$;
        """)


def downgrade():
    duplicates = op.get_bind().execute(sa.text(
        "SELECT result_id FROM po_line GROUP BY result_id HAVING COUNT(*) > 1 LIMIT 1"
    )).first()
    if duplicates:
        raise RuntimeError("Cannot downgrade while split-order lines exist; restore a pre-upgrade backup instead")
    with op.batch_alter_table("po_line", table_args=(
        sa.CheckConstraint("quantity > 0", name="ck_po_line_quantity_positive"),
        sa.CheckConstraint("unit_price > 0", name="ck_po_line_unit_price_positive"),
    )) as batch:
        batch.drop_constraint("uq_po_line_result_draft", type_="unique")
        batch.create_unique_constraint("po_line_result_id_key", ["result_id"])
    op.drop_index("ix_sourcing_decision_result_id", table_name="sourcing_decision")
    op.drop_table("sourcing_decision")
    for table in ("approval_delegation", "approval_matrix_rule", "match_result", "supplier_invoice_line",
                  "supplier_invoice", "goods_receipt_line", "goods_receipt", "budget"):
        op.drop_table(table)
    with op.batch_alter_table("po_line", table_args=(
        sa.CheckConstraint("quantity > 0", name="ck_po_line_quantity_positive"),
        sa.CheckConstraint("unit_price > 0", name="ck_po_line_unit_price_positive"),
    )) as batch:
        for col in ("open_quantity", "returned_quantity", "received_quantity"):
            batch.drop_column(col)
    with op.batch_alter_table("po_draft") as batch:
        for col in ("exchange_rate_source", "exchange_rate_date", "exchange_rate", "base_currency", "landed_cost",
                    "duty", "freight", "tax", "budget_code", "project_code", "cost_center", "lifecycle_status"):
            batch.drop_column(col)
    op.drop_table("sku_inventory_policy")
    op.drop_table("commercial_agreement")
    op.drop_table("supplier_performance")
