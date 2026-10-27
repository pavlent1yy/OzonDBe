"""ozon_actions, ozon_action_candidates, ozon_action_products

Revision ID: 0004
Revises: 0003
"""
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

COMMON = """
    raw           jsonb       NOT NULL,
    first_seen_at timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now(),
    is_deleted    boolean     NOT NULL DEFAULT false
"""

ACTION_PRODUCT = """
    action_id        bigint,
    product_id       bigint,
    price            numeric(14, 2),
    action_price     numeric(14, 2),
    max_action_price numeric(14, 2),
    currency         text,
"""


def upgrade() -> None:
    op.execute(f"""
        CREATE TABLE ozon_actions (
            action_id        bigint PRIMARY KEY,
            title            text,
            action_type      text,
            date_start       timestamptz,
            date_end         timestamptz,
            is_participating boolean,
            {COMMON}
        )
    """)
    op.execute(f"""
        CREATE TABLE ozon_action_candidates (
            {ACTION_PRODUCT}
            {COMMON},
            PRIMARY KEY (action_id, product_id)
        )
    """)
    op.execute(f"""
        CREATE TABLE ozon_action_products (
            {ACTION_PRODUCT}
            stock    integer,
            add_mode text,
            {COMMON},
            PRIMARY KEY (action_id, product_id)
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ozon_action_products")
    op.execute("DROP TABLE IF EXISTS ozon_action_candidates")
    op.execute("DROP TABLE IF EXISTS ozon_actions")
