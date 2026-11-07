"""Keep the uploader of every (immutable) upload revision.

``upload_revisions`` is append-only, so ``ON DELETE SET NULL`` on
``uploaded_by_user_id`` could never work: deleting such a user failed on the
append-only trigger instead of a clear rule. Users are deactivated, never
deleted, in this application; this makes the rule explicit (RESTRICT), so the
audit trail keeps who uploaded each file.

Only the foreign key's delete action changes; no rows are touched.

Revision ID: 0012_upload_uploader_restrict
Revises: 0011_sales_uploads
Create Date: 2026-11-07
"""

from alembic import op

revision = "0012_upload_uploader_restrict"
down_revision = "0011_sales_uploads"
branch_labels = None
depends_on = None

FK = "upload_revisions_uploaded_by_user_id_fkey"


def upgrade() -> None:
    op.drop_constraint(FK, "upload_revisions", type_="foreignkey")
    op.create_foreign_key(
        FK, "upload_revisions", "users", ["uploaded_by_user_id"], ["id"], ondelete="RESTRICT"
    )


def downgrade() -> None:
    op.drop_constraint(FK, "upload_revisions", type_="foreignkey")
    op.create_foreign_key(
        FK, "upload_revisions", "users", ["uploaded_by_user_id"], ["id"], ondelete="SET NULL"
    )
