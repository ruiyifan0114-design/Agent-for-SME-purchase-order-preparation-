"""agent audit, replay and proposal workflow

Revision ID: f9a1c2d3e4b5
Revises: e8f6b0d3a521
"""
from alembic import op
import sqlalchemy as sa

revision = "f9a1c2d3e4b5"
down_revision = "e8f6b0d3a521"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("agent_interaction",
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspace.id"), nullable=False),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("procurement_run.id")),
        sa.Column("replay_of_id", sa.String(36), sa.ForeignKey("agent_interaction.id")),
        sa.Column("user_id", sa.String(100), nullable=False), sa.Column("actor", sa.String(200), nullable=False),
        sa.Column("role", sa.String(30), nullable=False), sa.Column("status", sa.String(30), nullable=False),
        sa.Column("provider", sa.String(80), nullable=False), sa.Column("model_name", sa.String(100), nullable=False),
        sa.Column("prompt_version", sa.String(40), nullable=False),
        sa.Column("agent_config_version", sa.String(40), nullable=False),
        sa.Column("tool_definitions_version", sa.String(40), nullable=False),
        sa.Column("request", sa.JSON(), nullable=False), sa.Column("tool_definitions", sa.JSON(), nullable=False),
        sa.Column("tool_trace", sa.JSON(), nullable=False), sa.Column("final_outcome", sa.JSON()),
        sa.Column("input_tokens", sa.Integer(), nullable=False), sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("estimated_cost_usd", sa.Numeric(18, 8), nullable=False),
        sa.Column("correlation_id", sa.String(64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)), sa.Column("id", sa.String(36), primary_key=True))
    for col in ("workspace_id", "run_id", "replay_of_id", "status"):
        op.create_index(f"ix_agent_interaction_{col}", "agent_interaction", [col])
    op.create_table("agent_proposal",
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspace.id"), nullable=False),
        sa.Column("interaction_id", sa.String(36), sa.ForeignKey("agent_interaction.id")),
        sa.Column("proposal_type", sa.String(50), nullable=False), sa.Column("target_type", sa.String(50), nullable=False),
        sa.Column("target_id", sa.String(36), nullable=False), sa.Column("expected_version", sa.Integer(), nullable=False),
        sa.Column("exact_change", sa.JSON(), nullable=False), sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False), sa.Column("created_by", sa.String(200), nullable=False),
        sa.Column("confirmed_by", sa.String(200)), sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("executed_at", sa.DateTime(timezone=True)), sa.Column("execution_result", sa.JSON()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("id", sa.String(36), primary_key=True))
    for col in ("workspace_id", "interaction_id", "proposal_type", "target_id", "status"):
        op.create_index(f"ix_agent_proposal_{col}", "agent_proposal", [col])
    if op.get_bind().dialect.name == "postgresql":
        op.execute("REVOKE ALL ON agent_interaction, agent_proposal FROM anon, authenticated")


def downgrade():
    op.drop_table("agent_proposal")
    op.drop_table("agent_interaction")
