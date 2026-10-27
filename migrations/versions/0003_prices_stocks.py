"""ozon_product_prices, ozon_stocks_rfbs, ozon_stock_management

Revision ID: 0003
Revises: 0002
"""
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

COMMON = """
    raw           jsonb       NOT NULL,
    first_seen_at timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now(),
    is_deleted    boolean     NOT NULL DEFAULT false
"""


def upgrade() -> None:
    op.execute(f"""
        CREATE TABLE ozon_product_prices (
            product_id      bigint PRIMARY KEY,
            offer_id        text,
            price           numeric(14, 2),
            old_price       numeric(14, 2),
            min_price       numeric(14, 2),
            marketing_price numeric(14, 2),
            currency_code   text,
            {COMMON}
        )
    """)
    op.execute(f"""
        CREATE TABLE ozon_stocks_rfbs (
            sku            bigint,
            warehouse_id   bigint,
            product_id     bigint,
            offer_id       text,
            warehouse_name text,
            present        integer,
            reserved       integer,
            {COMMON},
            PRIMARY KEY (sku, warehouse_id)
        )
    """)
    op.execute(f"""
        CREATE TABLE ozon_stock_management (
            product_id bigint,
            type       text,
            offer_id   text,
            sku        bigint,
            present    integer,
            reserved   integer,
            {COMMON},
            PRIMARY KEY (product_id, type)
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ozon_stock_management")
    op.execute("DROP TABLE IF EXISTS ozon_stocks_rfbs")
    op.execute("DROP TABLE IF EXISTS ozon_product_prices")
