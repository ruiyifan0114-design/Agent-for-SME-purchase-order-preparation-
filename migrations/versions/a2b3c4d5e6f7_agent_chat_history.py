"""persistent agent conversations and messages

Revision ID: a2b3c4d5e6f7
Revises: f9a1c2d3e4b5
"""
from alembic import op
import sqlalchemy as sa

revision = "a2b3c4d5e6f7"
down_revision = "f9a1c2d3e4b5"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("agent_conversation",
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspace.id"), nullable=False),
        sa.Column("owner_id", sa.String(200), nullable=False),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("procurement_run.id")),
        sa.Column("created_by", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(36), primary_key=True))
    for col in ("workspace_id", "owner_id", "run_id", "updated_at"):
        op.create_index(f"ix_agent_conversation_{col}", "agent_conversation", [col])
    op.create_table("agent_chat_message",
        sa.Column("conversation_id", sa.String(36), sa.ForeignKey("agent_conversation.id"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("interaction_id", sa.String(36), sa.ForeignKey("agent_interaction.id")),
        sa.Column("message_metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(36), primary_key=True),
        sa.UniqueConstraint("conversation_id", "sequence"))
    for col in ("conversation_id", "interaction_id", "created_at"):
        op.create_index(f"ix_agent_chat_message_{col}", "agent_chat_message", [col])
    if op.get_bind().dialect.name == "postgresql":
        op.execute("REVOKE ALL ON agent_conversation, agent_chat_message FROM anon, authenticated")


def downgrade():
    op.drop_table("agent_chat_message")
    op.drop_table("agent_conversation")
