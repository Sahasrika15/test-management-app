"""track source file for test cases

Revision ID: 4bad7de3aa67
Revises: 7947883a3a0a
Create Date: 2026-10-15 10:46:56.833378

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4bad7de3aa67'
down_revision: Union[str, Sequence[str], None] = '7947883a3a0a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("test_cases", sa.Column("source_file", sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column("test_cases", "source_file")