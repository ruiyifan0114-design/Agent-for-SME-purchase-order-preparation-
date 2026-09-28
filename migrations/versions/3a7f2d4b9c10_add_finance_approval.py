"""add finance approval stage

Revision ID: 3a7f2d4b9c10
Revises: 98d40bd9e7ec
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "3a7f2d4b9c10"
down_revision: Union[str, None] = "98d40bd9e7ec"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("po_draft", sa.Column("finance_reviewer", sa.String(length=200), nullable=True))
    op.add_column("po_draft", sa.Column("finance_approved_at", sa.DateTime(timezone=True), nullable=True))
    # Existing high-value approvals must pass the newly required Finance stage.
    op.execute("UPDATE po_draft SET status = 'FINANCE_REVIEW', version = version + 1 "
               "WHERE currency = 'SGD' AND total >= 5000 AND status = 'APPROVED'")


def downgrade() -> None:
    op.execute("UPDATE po_draft SET status = 'NEEDS_REVIEW', reviewer = NULL, approved_at = NULL, "
               "version = version + 1 WHERE status = 'FINANCE_REVIEW'")
    op.drop_column("po_draft", "finance_approved_at")
    op.drop_column("po_draft", "finance_reviewer")
