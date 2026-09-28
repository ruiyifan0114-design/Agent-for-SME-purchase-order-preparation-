"""restrict direct Supabase Data API access

Revision ID: 7b21e9c46f30
Revises: 3a7f2d4b9c10
"""

from typing import Sequence, Union

from alembic import op

revision: str = "7b21e9c46f30"
down_revision: Union[str, None] = "3a7f2d4b9c10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Keep procurement data behind FastAPI when Supabase roles exist."""
    if op.get_bind().dialect.name != "postgresql":
        return

    op.execute(
        """
        DO $$
        DECLARE api_role text;
        BEGIN
          FOR api_role IN
            SELECT rolname FROM pg_roles WHERE rolname IN ('anon', 'authenticated')
          LOOP
            EXECUTE format('REVOKE USAGE ON SCHEMA public FROM %I', api_role);
            EXECUTE format(
              'REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM %I', api_role
            );
            EXECUTE format(
              'REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM %I', api_role
            );
            EXECUTE format(
              'REVOKE ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA public FROM %I', api_role
            );
            EXECUTE format(
              'ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM %I',
              api_role
            );
            EXECUTE format(
              'ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM %I',
              api_role
            );
            EXECUTE format(
              'ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON FUNCTIONS FROM %I',
              api_role
            );
          END LOOP;
        END $$;
        """
    )


def downgrade() -> None:
    # Security grants are deliberately not restored by a schema downgrade.
    pass
