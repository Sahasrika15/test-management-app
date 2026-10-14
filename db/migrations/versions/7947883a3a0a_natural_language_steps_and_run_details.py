"""natural language steps and run details

Revision ID: 7947883a3a0a
Revises: ec26bcbfa434
Create Date: 2026-10-14 15:29:52.008459

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7947883a3a0a'
down_revision: Union[str, Sequence[str], None] = 'ec26bcbfa434'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("test_cases", "module_name")
    op.drop_column("test_cases", "action_name")
    op.drop_column("test_cases", "test_data")
    op.add_column("test_cases", sa.Column("page", sa.String(255), nullable=False))
    op.add_column("test_cases", sa.Column("steps", sa.Text(), nullable=False))
    op.add_column("executions", sa.Column("app_url", sa.String(500), nullable=False))
    op.add_column("executions", sa.Column("app_name", sa.String(255), nullable=True))
    op.add_column("test_results", sa.Column("failed_step", sa.Integer(), nullable=True))
    op.add_column("test_results", sa.Column("video_path", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("test_results", "video_path")
    op.drop_column("test_results", "failed_step")
    op.drop_column("executions", "app_name")
    op.drop_column("executions", "app_url")
    op.drop_column("test_cases", "steps")
    op.drop_column("test_cases", "page")
    op.add_column("test_cases", sa.Column("test_data", sa.Text(), nullable=True))
    op.add_column("test_cases", sa.Column("action_name", sa.String(255), nullable=True))
    op.add_column("test_cases", sa.Column("module_name", sa.String(100), nullable=True))