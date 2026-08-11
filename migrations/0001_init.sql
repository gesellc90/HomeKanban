-- 0001_init.sql — Domänenschema (docs/PLAN.md §3).
--
-- schema_migrations wird vom Migrationsrunner selbst angelegt (app/migrate.py,
-- CREATE TABLE IF NOT EXISTS) und daher hier bewusst nicht noch einmal erzeugt.

CREATE TABLE categories (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    position INTEGER NOT NULL
);

CREATE TABLE stores (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    position INTEGER NOT NULL
);

CREATE TABLE items (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    unit TEXT NOT NULL,
    note TEXT,
    stock INTEGER NOT NULL,
    reorder_level INTEGER NOT NULL,
    target_stock INTEGER NOT NULL,
    pack_size INTEGER NOT NULL DEFAULT 1,
    category_id INTEGER REFERENCES categories (id),
    store_id INTEGER REFERENCES stores (id),
    qr_token TEXT NOT NULL UNIQUE,
    position INTEGER NOT NULL,
    archived_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (stock >= 0),
    CHECK (reorder_level >= 0),
    CHECK (pack_size >= 1),
    CHECK (target_stock > reorder_level)
);

-- Artikelname eindeutig unter den nicht archivierten Artikeln (COLLATE NOCASE).
CREATE UNIQUE INDEX ux_items_name_active
    ON items (name COLLATE NOCASE)
    WHERE archived_at IS NULL;

CREATE TABLE shopping_lists (
    id INTEGER PRIMARY KEY,
    status TEXT NOT NULL CHECK (status IN ('open', 'done', 'cancelled')),
    created_at TEXT NOT NULL,
    closed_at TEXT,
    exported_at TEXT,
    export_count INTEGER NOT NULL DEFAULT 0
);

-- Höchstens eine offene Liste gleichzeitig.
CREATE UNIQUE INDEX ux_shopping_lists_one_open
    ON shopping_lists (status)
    WHERE status = 'open';

CREATE TABLE shopping_list_lines (
    id INTEGER PRIMARY KEY,
    list_id INTEGER NOT NULL REFERENCES shopping_lists (id),
    item_id INTEGER NOT NULL REFERENCES items (id),
    suggested_qty INTEGER NOT NULL,
    purchased_qty INTEGER,
    name_snapshot TEXT NOT NULL,
    unit_snapshot TEXT NOT NULL,
    position INTEGER NOT NULL,
    checked_at TEXT,
    dropped_at TEXT
);

-- Ein Artikel hat höchstens eine nicht verworfene Position je Liste.
CREATE UNIQUE INDEX ux_shopping_list_lines_active
    ON shopping_list_lines (list_id, item_id)
    WHERE dropped_at IS NULL;

CREATE TABLE movements (
    id INTEGER PRIMARY KEY,
    item_id INTEGER NOT NULL REFERENCES items (id),
    kind TEXT NOT NULL CHECK (kind IN ('opening', 'withdrawal', 'restock', 'adjustment')),
    delta INTEGER NOT NULL,
    stock_after INTEGER NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('qr', 'board', 'shopping_list', 'import')),
    line_id INTEGER REFERENCES shopping_list_lines (id),
    idempotency_key TEXT UNIQUE,
    reverts_movement_id INTEGER UNIQUE REFERENCES movements (id),
    note TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX ix_movements_item_created ON movements (item_id, created_at);
