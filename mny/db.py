import os
import sqlite3
from pathlib import Path
from contextlib import contextmanager


def get_db_path() -> Path:
    home = Path(os.path.expanduser("~"))
    mny_dir = home / ".mny"
    mny_dir.mkdir(exist_ok=True)
    return mny_dir / "finance.db"


DB_PATH = get_db_path()


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    type TEXT DEFAULT 'cash',
    balance REAL DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    type TEXT NOT NULL CHECK(type IN ('income','expense')),
    parent_id INTEGER,
    FOREIGN KEY (parent_id) REFERENCES categories(id)
);

CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL CHECK(type IN ('income','expense')),
    amount REAL NOT NULL,
    account_id INTEGER NOT NULL,
    category_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    note TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (account_id) REFERENCES accounts(id),
    FOREIGN KEY (category_id) REFERENCES categories(id)
);

CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS transaction_tags (
    transaction_id INTEGER NOT NULL,
    tag_id INTEGER NOT NULL,
    PRIMARY KEY (transaction_id, tag_id),
    FOREIGN KEY (transaction_id) REFERENCES transactions(id) ON DELETE CASCADE,
    FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS budgets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scope TEXT NOT NULL CHECK(scope IN ('category','account','tag','project')) DEFAULT 'category',
    scope_key TEXT NOT NULL,
    year INTEGER NOT NULL,
    month INTEGER NOT NULL,
    amount REAL NOT NULL,
    carry_over REAL DEFAULT 0,
    UNIQUE (scope, scope_key, year, month)
);

CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS transaction_projects (
    transaction_id INTEGER NOT NULL,
    project_id INTEGER NOT NULL,
    PRIMARY KEY (transaction_id, project_id),
    FOREIGN KEY (transaction_id) REFERENCES transactions(id) ON DELETE CASCADE,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_tx_date ON transactions(date);
CREATE INDEX IF NOT EXISTS idx_tx_account ON transactions(account_id);
CREATE INDEX IF NOT EXISTS idx_tx_category ON transactions(category_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_tx_unique ON transactions(type, amount, account_id, category_id, date, COALESCE(note, ''));

CREATE TABLE IF NOT EXISTS transfers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_account_id INTEGER NOT NULL,
    to_account_id INTEGER NOT NULL,
    amount REAL NOT NULL,
    date TEXT NOT NULL,
    note TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (from_account_id) REFERENCES accounts(id),
    FOREIGN KEY (to_account_id) REFERENCES accounts(id)
);
CREATE INDEX IF NOT EXISTS idx_transfer_date ON transfers(date);
CREATE INDEX IF NOT EXISTS idx_transfer_from ON transfers(from_account_id);
CREATE INDEX IF NOT EXISTS idx_transfer_to ON transfers(to_account_id);

CREATE TABLE IF NOT EXISTS recurring (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL CHECK(type IN ('income','expense')),
    amount REAL NOT NULL,
    account_id INTEGER NOT NULL,
    category_id INTEGER NOT NULL,
    frequency TEXT NOT NULL CHECK(frequency IN ('daily','weekly','monthly','yearly')),
    interval_day INTEGER,
    start_date TEXT NOT NULL,
    end_date TEXT,
    last_generated TEXT,
    next_date TEXT NOT NULL,
    note TEXT,
    tags TEXT,
    active INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (account_id) REFERENCES accounts(id),
    FOREIGN KEY (category_id) REFERENCES categories(id)
);
CREATE INDEX IF NOT EXISTS idx_recurring_next ON recurring(next_date);
"""

DEFAULT_ACCOUNTS = [
    ("现金", "cash"),
    ("银行卡", "bank"),
    ("支付宝", "alipay"),
    ("微信", "wechat"),
    ("信用卡", "credit"),
]

DEFAULT_CATEGORIES = [
    ("工资", "income"),
    ("奖金", "income"),
    ("投资收益", "income"),
    ("其他收入", "income"),
    ("餐饮", "expense"),
    ("交通", "expense"),
    ("购物", "expense"),
    ("娱乐", "expense"),
    ("居住", "expense"),
    ("医疗", "expense"),
    ("教育", "expense"),
    ("通讯", "expense"),
    ("其他支出", "expense"),
]


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        try:
            old = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='budgets'"
            ).fetchone()
            cols = [r[1] for r in conn.execute("PRAGMA table_info(budgets)").fetchall()]
            if old and "category_id" in cols and "scope" not in cols:
                rows = conn.execute(
                    "SELECT category_id, year, month, amount FROM budgets"
                ).fetchall()
                conn.execute("DROP TABLE budgets")
                conn.executescript("""
CREATE TABLE IF NOT EXISTS budgets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scope TEXT NOT NULL CHECK(scope IN ('category','account','tag','project')) DEFAULT 'category',
    scope_key TEXT NOT NULL,
    year INTEGER NOT NULL,
    month INTEGER NOT NULL,
    amount REAL NOT NULL,
    carry_over REAL DEFAULT 0,
    UNIQUE (scope, scope_key, year, month)
);
                """)
                for r in rows:
                    cat_name = conn.execute(
                        "SELECT name FROM categories WHERE id=?", (r["category_id"],)
                    ).fetchone()
                    if cat_name:
                        conn.execute(
                            "INSERT INTO budgets (scope, scope_key, year, month, amount) VALUES (?, ?, ?, ?, ?)",
                            ("category", cat_name["name"], r["year"], r["month"], r["amount"]),
                        )
            if "carry_over" not in cols:
                try:
                    conn.execute("ALTER TABLE budgets ADD COLUMN carry_over REAL DEFAULT 0")
                except Exception:
                    pass
        except Exception:
            pass
        for name, atype in DEFAULT_ACCOUNTS:
            conn.execute(
                "INSERT OR IGNORE INTO accounts (name, type) VALUES (?, ?)",
                (name, atype),
            )
        for name, ctype in DEFAULT_CATEGORIES:
            conn.execute(
                "INSERT OR IGNORE INTO categories (name, type) VALUES (?, ?)",
                (name, ctype),
            )
