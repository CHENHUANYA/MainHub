"""Persist import identity independently of mutable work-order content."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260923_0011"
down_revision = "20260921_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("work_orders", sa.Column("import_key", sa.String(64), nullable=True))
    op.add_column("work_orders", sa.Column("import_metadata", postgresql.JSONB(), nullable=True))
    op.create_unique_constraint("uq_work_orders_import_key", "work_orders", ["import_key"])


def downgrade() -> None:
    op.drop_constraint("uq_work_orders_import_key", "work_orders", type_="unique")
    op.drop_column("work_orders", "import_metadata")
    op.drop_column("work_orders", "import_key")
