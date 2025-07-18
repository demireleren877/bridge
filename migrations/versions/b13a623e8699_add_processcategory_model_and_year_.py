"""Add ProcessCategory model and year field to Process

Revision ID: b13a623e8699
Revises: 
Create Date: 2025-05-31 19:57:00.750906

"""
from alembic import op
import sqlalchemy as sa
from datetime import datetime
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision = 'b13a623e8699'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    # Mevcut süreçlerin yıllarını güncelle
    connection = op.get_bind()
    processes = connection.execute(text('SELECT id, created_at FROM process')).fetchall()
    for process_id, created_at_str in processes:
        try:
            created_at = datetime.strptime(created_at_str, '%Y-%m-%d %H:%M:%S.%f')
            year = created_at.year
        except (ValueError, TypeError):
            year = datetime.now().year
            
        connection.execute(
            text('UPDATE process SET year = :year WHERE id = :id'),
            {'year': year, 'id': process_id}
        )

    # Year sütununu not null yap
    with op.batch_alter_table('process', schema=None) as batch_op:
        batch_op.alter_column('year',
            existing_type=sa.Integer(),
            nullable=False
        )

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('process', schema=None) as batch_op:
        batch_op.alter_column('year',
            existing_type=sa.Integer(),
            nullable=True
        )
    # ### end Alembic commands ###
