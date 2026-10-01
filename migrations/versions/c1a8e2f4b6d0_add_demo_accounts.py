"""add demo accounts and sessions

Revision ID: c1a8e2f4b6d0
Revises: 8d34fa21c670
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c1a8e2f4b6d0"
down_revision: Union[str, None] = "8d34fa21c670"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "demo_account",
        sa.Column("username", sa.String(32), nullable=False),
        sa.Column("display_name", sa.String(32), nullable=False),
        sa.Column("password_hash", sa.String(256), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(36), primary_key=True),
    )
    op.create_index("ix_demo_account_username", "demo_account", ["username"], unique=True)
    op.create_table(
        "demo_session",
        sa.Column("account_id", sa.String(36), sa.ForeignKey("demo_account.id"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(36), primary_key=True),
    )
    op.create_index("ix_demo_session_account_id", "demo_session", ["account_id"])
    op.create_index("ix_demo_session_token_hash", "demo_session", ["token_hash"], unique=True)
    op.create_index("ix_demo_session_expires_at", "demo_session", ["expires_at"])
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            """
            DO $$ DECLARE api_role text; BEGIN
              FOR api_role IN SELECT rolname FROM pg_roles WHERE rolname IN ('anon', 'authenticated') LOOP
                EXECUTE format(
                  'REVOKE ALL PRIVILEGES ON TABLE demo_account, demo_session FROM %I', api_role
                );
              END LOOP;
            END $$;
            """
        )


def downgrade() -> None:
    op.drop_index("ix_demo_session_expires_at", table_name="demo_session")
    op.drop_index("ix_demo_session_token_hash", table_name="demo_session")
    op.drop_index("ix_demo_session_account_id", table_name="demo_session")
    op.drop_table("demo_session")
    op.drop_index("ix_demo_account_username", table_name="demo_account")
    op.drop_table("demo_account")
