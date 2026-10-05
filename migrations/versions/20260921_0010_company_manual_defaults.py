"""Remove company-specific implicit defaults without changing existing rows."""
from alembic import op
import sqlalchemy as sa

revision = "20260921_0010"
down_revision = "20260902_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("alarm_events", "issues", "work_orders"):
        op.alter_column(table, "manual", existing_type=sa.String(64), server_default="")


def downgrade() -> None:
    for table in ("alarm_events", "issues", "work_orders"):
        op.alter_column(table, "manual", existing_type=sa.String(64), server_default="808d")
