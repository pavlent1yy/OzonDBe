"""ozon_warehouses, ozon_delivery_methods, ozon_products

Revision ID: 0002
Revises: 0001
"""
from alembic import op

revision = "0002"
down_revision = "0001"
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
        CREATE TABLE ozon_warehouses (
            warehouse_id bigint PRIMARY KEY,
            name         text,
            is_rfbs      boolean,
            status       text,
            {COMMON}
        )
    """)
    op.execute(f"""
        CREATE TABLE ozon_delivery_methods (
            id           bigint PRIMARY KEY,
            warehouse_id bigint,
            name         text,
            status       text,
            provider_id  bigint,
            {COMMON}
        )
    """)
    op.execute(f"""
        CREATE TABLE ozon_products (
            product_id bigint PRIMARY KEY,
            offer_id   text,
            name       text,
            archived   boolean,
            {COMMON}
        )
    """)
    op.execute("CREATE INDEX ozon_products_offer_id_idx ON ozon_products (offer_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ozon_products")
    op.execute("DROP TABLE IF EXISTS ozon_delivery_methods")
    op.execute("DROP TABLE IF EXISTS ozon_warehouses")
