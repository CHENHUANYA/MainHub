"""Persist import batch history alongside imported business records."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '20260924_0012'
down_revision = '20260923_0011'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('import_batches',
        sa.Column('batch_id', sa.String(64), primary_key=True),
        sa.Column('kind', sa.String(32), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('payload', postgresql.JSONB(), nullable=False))
    op.create_index('ix_import_batches_created_at', 'import_batches', ['created_at', 'batch_id'])


def downgrade():
    op.drop_index('ix_import_batches_created_at', table_name='import_batches')
    op.drop_table('import_batches')
