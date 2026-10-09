"""initial auditable causal platform schema

Revision ID: 20260719_0001
Revises:
Create Date: 2026-07-19
"""

from __future__ import annotations

from alembic import op
from benmo_backend import models  # noqa: F401
from benmo_backend.db import Base

revision = "20260719_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)

    if bind.dialect.name == "postgresql":
        op.execute(
            """
            CREATE OR REPLACE FUNCTION benmo_reject_locked_verification_spec_change()
            RETURNS trigger AS $$
            BEGIN
              IF OLD.locked_at IS NOT NULL THEN
                RAISE EXCEPTION
                  'locked verification_specs are immutable; insert a new spec_version';
              END IF;
              RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_verification_specs_no_update
            BEFORE UPDATE ON verification_specs
            FOR EACH ROW EXECUTE FUNCTION benmo_reject_locked_verification_spec_change();
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_verification_specs_no_delete
            BEFORE DELETE ON verification_specs
            FOR EACH ROW EXECUTE FUNCTION benmo_reject_locked_verification_spec_change();
            """
        )
    elif bind.dialect.name == "sqlite":
        op.execute(
            """
            CREATE TRIGGER trg_verification_specs_no_update
            BEFORE UPDATE ON verification_specs
            WHEN OLD.locked_at IS NOT NULL
            BEGIN
              SELECT RAISE(ABORT,
                'locked verification_specs are immutable; insert a new spec_version');
            END;
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_verification_specs_no_delete
            BEFORE DELETE ON verification_specs
            WHEN OLD.locked_at IS NOT NULL
            BEGIN
              SELECT RAISE(ABORT, 'locked verification_specs cannot be deleted');
            END;
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_verification_specs_no_update ON verification_specs")
        op.execute("DROP TRIGGER IF EXISTS trg_verification_specs_no_delete ON verification_specs")
        op.execute("DROP FUNCTION IF EXISTS benmo_reject_locked_verification_spec_change()")
    elif bind.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_verification_specs_no_update")
        op.execute("DROP TRIGGER IF EXISTS trg_verification_specs_no_delete")
    Base.metadata.drop_all(bind=bind)
