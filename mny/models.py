from datetime import datetime, date, timedelta
from typing import Optional, List, Dict, Any, Tuple
from .db import get_conn


def _row_to_dict(row) -> Dict[str, Any]:
    return dict(row) if row else None


def get_account(name_or_id: str | int) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        if isinstance(name_or_id, int) or (isinstance(name_or_id, str) and name_or_id.isdigit()):
            row = conn.execute("SELECT * FROM accounts WHERE id = ?", (int(name_or_id),)).fetchone()
        else:
            row = conn.execute("SELECT * FROM accounts WHERE name = ?", (name_or_id,)).fetchone()
        return _row_to_dict(row)


def list_accounts() -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM accounts ORDER BY id").fetchall()
        return [_row_to_dict(r) for r in rows]


def add_account(name: str, atype: str = "cash", initial_balance: float = 0.0) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO accounts (name, type, balance) VALUES (?, ?, ?)",
            (name, atype, initial_balance),
        )
        return cur.lastrowid


def get_category(name_or_id: str | int, ctype: Optional[str] = None) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        params = []
        sql = "SELECT * FROM categories WHERE "
        if isinstance(name_or_id, int) or (isinstance(name_or_id, str) and name_or_id.isdigit()):
            sql += "id = ?"
            params.append(int(name_or_id))
        else:
            sql += "name = ?"
            params.append(name_or_id)
        if ctype:
            sql += " AND type = ?"
            params.append(ctype)
        row = conn.execute(sql, params).fetchone()
        return _row_to_dict(row)


def list_categories(ctype: Optional[str] = None) -> List[Dict[str, Any]]:
    with get_conn() as conn:
        if ctype:
            rows = conn.execute("SELECT * FROM categories WHERE type = ? ORDER BY name", (ctype,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM categories ORDER BY type, name").fetchall()
        return [_row_to_dict(r) for r in rows]


def add_category(name: str, ctype: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO categories (name, type) VALUES (?, ?)",
            (name, ctype),
        )
        return cur.lastrowid


def _get_or_create_tag(conn, name: str) -> int:
    row = conn.execute("SELECT id FROM tags WHERE name = ?", (name,)).fetchone()
    if row:
        return row["id"]
    cur = conn.execute("INSERT INTO tags (name) VALUES (?)", (name,))
    return cur.lastrowid


def add_transaction(
    tx_type: str,
    amount: float,
    account: str | int,
    category: str | int,
    tx_date: Optional[str] = None,
    note: Optional[str] = None,
    tags: Optional[List[str]] = None,
) -> int:
    acc = get_account(account)
    if not acc:
        raise ValueError(f"账户不存在: {account}")
    cat = get_category(category, tx_type)
    if not cat:
        raise ValueError(f"分类不存在或类型不匹配: {category}")
    if tx_date is None:
        tx_date = date.today().isoformat()
    else:
        datetime.strptime(tx_date, "%Y-%m-%d")

    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO transactions (type, amount, account_id, category_id, date, note)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (tx_type, amount, acc["id"], cat["id"], tx_date, note),
        )
        tx_id = cur.lastrowid

        sign = 1 if tx_type == "income" else -1
        conn.execute(
            "UPDATE accounts SET balance = balance + ? WHERE id = ?",
            (sign * amount, acc["id"]),
        )

        if tags:
            for tag_name in tags:
                tag_id = _get_or_create_tag(conn, tag_name.strip())
                conn.execute(
                    "INSERT OR IGNORE INTO transaction_tags (transaction_id, tag_id) VALUES (?, ?)",
                    (tx_id, tag_id),
                )
        return tx_id


def _assemble_tx(conn, row) -> Dict[str, Any]:
    d = _row_to_dict(row)
    if not d:
        return d
    tag_rows = conn.execute(
        """SELECT t.name FROM tags t
           JOIN transaction_tags tt ON t.id = tt.tag_id
           WHERE tt.transaction_id = ?""",
        (d["id"],),
    ).fetchall()
    d["tags"] = [r["name"] for r in tag_rows]
    d["account"] = conn.execute("SELECT name FROM accounts WHERE id = ?", (d["account_id"],)).fetchone()["name"]
    d["category"] = conn.execute("SELECT name FROM categories WHERE id = ?", (d["category_id"],)).fetchone()["name"]
    return d


def get_transaction(tx_id: int) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM transactions WHERE id = ?", (tx_id,)).fetchone()
        return _assemble_tx(conn, row) if row else None


def list_transactions(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    tx_type: Optional[str] = None,
    account: Optional[str | int] = None,
    category: Optional[str | int] = None,
    keyword: Optional[str] = None,
    tag: Optional[str] = None,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    sql = "SELECT t.* FROM transactions t WHERE 1=1"
    params = []
    if start_date:
        sql += " AND t.date >= ?"
        params.append(start_date)
    if end_date:
        sql += " AND t.date <= ?"
        params.append(end_date)
    if tx_type:
        sql += " AND t.type = ?"
        params.append(tx_type)
    if account:
        acc = get_account(account)
        if acc:
            sql += " AND t.account_id = ?"
            params.append(acc["id"])
    if category:
        cat = get_category(category)
        if cat:
            sql += " AND t.category_id = ?"
            params.append(cat["id"])
    if keyword:
        sql += " AND (t.note LIKE ? OR EXISTS (SELECT 1 FROM categories c WHERE c.id = t.category_id AND c.name LIKE ?))"
        like = f"%{keyword}%"
        params.extend([like, like])
    if tag:
        sql += " AND EXISTS (SELECT 1 FROM transaction_tags tt JOIN tags tg ON tt.tag_id = tg.id WHERE tt.transaction_id = t.id AND tg.name = ?)"
        params.append(tag)
    sql += " ORDER BY t.date DESC, t.id DESC"
    if limit:
        sql += f" LIMIT {int(limit)}"

    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
        return [_assemble_tx(conn, r) for r in rows]


def update_transaction(
    tx_id: int,
    tx_type: Optional[str] = None,
    amount: Optional[float] = None,
    account: Optional[str | int] = None,
    category: Optional[str | int] = None,
    tx_date: Optional[str] = None,
    note: Optional[str] = None,
    tags: Optional[List[str]] = None,
) -> bool:
    existing = get_transaction(tx_id)
    if not existing:
        raise ValueError(f"交易不存在: {tx_id}")

    updates = []
    params = []

    new_type = tx_type if tx_type else existing["type"]
    new_amount = amount if amount is not None else existing["amount"]
    new_acc_id = get_account(account)["id"] if account else existing["account_id"]
    new_cat_id = get_category(category, new_type)["id"] if category else existing["category_id"]
    new_date = tx_date if tx_date else existing["date"]
    new_note = note if note is not None else existing["note"]

    with get_conn() as conn:
        old_sign = 1 if existing["type"] == "income" else -1
        conn.execute(
            "UPDATE accounts SET balance = balance - ? WHERE id = ?",
            (old_sign * existing["amount"], existing["account_id"]),
        )
        new_sign = 1 if new_type == "income" else -1
        conn.execute(
            "UPDATE accounts SET balance = balance + ? WHERE id = ?",
            (new_sign * new_amount, new_acc_id),
        )

        conn.execute(
            """UPDATE transactions
               SET type=?, amount=?, account_id=?, category_id=?, date=?, note=?, updated_at=datetime('now')
               WHERE id=?""",
            (new_type, new_amount, new_acc_id, new_cat_id, new_date, new_note, tx_id),
        )

        if tags is not None:
            conn.execute("DELETE FROM transaction_tags WHERE transaction_id = ?", (tx_id,))
            for tag_name in tags:
                tag_id = _get_or_create_tag(conn, tag_name.strip())
                conn.execute(
                    "INSERT OR IGNORE INTO transaction_tags (transaction_id, tag_id) VALUES (?, ?)",
                    (tx_id, tag_id),
                )
        return True


def delete_transaction(tx_id: int) -> bool:
    existing = get_transaction(tx_id)
    if not existing:
        raise ValueError(f"交易不存在: {tx_id}")
    with get_conn() as conn:
        sign = 1 if existing["type"] == "income" else -1
        conn.execute(
            "UPDATE accounts SET balance = balance - ? WHERE id = ?",
            (sign * existing["amount"], existing["account_id"]),
        )
        conn.execute("DELETE FROM transactions WHERE id = ?", (tx_id,))
        return True


def set_budget(category: str | int, year: int, month: int, amount: float) -> int:
    cat = get_category(category, "expense")
    if not cat:
        raise ValueError(f"支出分类不存在: {category}")
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO budgets (category_id, year, month, amount)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(category_id, year, month) DO UPDATE SET amount=excluded.amount""",
            (cat["id"], year, month, amount),
        )
        return cur.lastrowid


def list_budgets(year: int, month: int) -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT b.*, c.name AS category_name
               FROM budgets b JOIN categories c ON b.category_id = c.id
               WHERE b.year = ? AND b.month = ?
               ORDER BY c.name""",
            (year, month),
        ).fetchall()
        results = []
        for r in rows:
            d = _row_to_dict(r)
            spent = conn.execute(
                """SELECT COALESCE(SUM(amount),0) FROM transactions
                   WHERE type='expense' AND category_id=? AND strftime('%Y', date)=? AND strftime('%m', date)=?""",
                (r["category_id"], f"{year:04d}", f"{month:02d}"),
            ).fetchone()[0]
            d["spent"] = spent
            d["remaining"] = r["amount"] - spent
            results.append(d)
        return results


def get_monthly_summary(year: int, month: int) -> Dict[str, Any]:
    start = f"{year:04d}-{month:02d}-01"
    if month == 12:
        end = f"{year + 1:04d}-01-01"
    else:
        end = f"{year:04d}-{month + 1:02d}-01"
    with get_conn() as conn:
        income = conn.execute(
            "SELECT COALESCE(SUM(amount),0) FROM transactions WHERE type='income' AND date >= ? AND date < ?",
            (start, end),
        ).fetchone()[0]
        expense = conn.execute(
            "SELECT COALESCE(SUM(amount),0) FROM transactions WHERE type='expense' AND date >= ? AND date < ?",
            (start, end),
        ).fetchone()[0]
        by_cat = conn.execute(
            """SELECT c.name AS category, c.type, COALESCE(SUM(t.amount),0) AS total
               FROM categories c
               LEFT JOIN transactions t ON t.category_id = c.id AND t.date >= ? AND t.date < ?
               GROUP BY c.id
               HAVING total > 0
               ORDER BY c.type, total DESC""",
            (start, end),
        ).fetchall()
        return {
            "income": income,
            "expense": expense,
            "net": income - expense,
            "by_category": [_row_to_dict(r) for r in by_cat],
        }


def get_weekly_summary() -> Dict[str, Any]:
    today = date.today()
    start = today - timedelta(days=today.weekday())
    end = start + timedelta(days=7)
    with get_conn() as conn:
        income = conn.execute(
            "SELECT COALESCE(SUM(amount),0) FROM transactions WHERE type='income' AND date >= ? AND date < ?",
            (start.isoformat(), end.isoformat()),
        ).fetchone()[0]
        expense = conn.execute(
            "SELECT COALESCE(SUM(amount),0) FROM transactions WHERE type='expense' AND date >= ? AND date < ?",
            (start.isoformat(), end.isoformat()),
        ).fetchone()[0]
        by_cat = conn.execute(
            """SELECT c.name AS category, c.type, COALESCE(SUM(t.amount),0) AS total
               FROM categories c
               LEFT JOIN transactions t ON t.category_id = c.id AND t.date >= ? AND t.date < ?
               GROUP BY c.id
               HAVING total > 0
               ORDER BY c.type, total DESC""",
            (start.isoformat(), end.isoformat()),
        ).fetchall()
        return {
            "start": start.isoformat(),
            "end": (end - timedelta(days=1)).isoformat(),
            "income": income,
            "expense": expense,
            "net": income - expense,
            "by_category": [_row_to_dict(r) for r in by_cat],
        }


def get_yearly_summary(year: int) -> Dict[str, Any]:
    start = f"{year:04d}-01-01"
    end = f"{year + 1:04d}-01-01"
    with get_conn() as conn:
        income = conn.execute(
            "SELECT COALESCE(SUM(amount),0) FROM transactions WHERE type='income' AND date >= ? AND date < ?",
            (start, end),
        ).fetchone()[0]
        expense = conn.execute(
            "SELECT COALESCE(SUM(amount),0) FROM transactions WHERE type='expense' AND date >= ? AND date < ?",
            (start, end),
        ).fetchone()[0]
        by_cat = conn.execute(
            """SELECT c.name AS category, c.type, COALESCE(SUM(t.amount),0) AS total
               FROM categories c
               LEFT JOIN transactions t ON t.category_id = c.id AND t.date >= ? AND t.date < ?
               GROUP BY c.id
               HAVING total > 0
               ORDER BY c.type, total DESC""",
            (start, end),
        ).fetchall()
        by_month = conn.execute(
            """SELECT strftime('%m', date) AS month, type, COALESCE(SUM(amount),0) AS total
               FROM transactions
               WHERE date >= ? AND date < ?
               GROUP BY month, type
               ORDER BY month""",
            (start, end),
        ).fetchall()
        return {
            "year": year,
            "income": income,
            "expense": expense,
            "net": income - expense,
            "by_category": [_row_to_dict(r) for r in by_cat],
            "by_month": [_row_to_dict(r) for r in by_month],
        }


def get_account_balances() -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT a.id, a.name, a.type, a.balance,
                      COALESCE((SELECT SUM(amount) FROM transactions WHERE type='income' AND account_id=a.id),0) AS total_income,
                      COALESCE((SELECT SUM(amount) FROM transactions WHERE type='expense' AND account_id=a.id),0) AS total_expense
               FROM accounts a
               ORDER BY a.balance DESC"""
        ).fetchall()
        return [_row_to_dict(r) for r in rows]


def list_tags() -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM tags ORDER BY name").fetchall()
        return [_row_to_dict(r) for r in rows]


def find_duplicate(conn, tx_type: str, amount: float, account_id: int, category_id: int, tx_date: str, note: Optional[str]) -> Optional[int]:
    row = conn.execute(
        """SELECT id FROM transactions
           WHERE type=? AND amount=? AND account_id=? AND category_id=? AND date=? AND COALESCE(note,'')=?""",
        (tx_type, amount, account_id, category_id, tx_date, note or ""),
    ).fetchone()
    return row["id"] if row else None


def bulk_import(transactions: List[Dict[str, Any]]) -> Tuple[int, int]:
    added = 0
    skipped = 0
    with get_conn() as conn:
        for tx in transactions:
            try:
                acc = get_account(tx["account"])
                if not acc:
                    acc_id = conn.execute(
                        "INSERT INTO accounts (name, type, balance) VALUES (?, ?, 0)",
                        (tx["account"], "cash"),
                    ).lastrowid
                else:
                    acc_id = acc["id"]

                cat = get_category(tx["category"], tx["type"])
                if not cat:
                    cat_id = conn.execute(
                        "INSERT INTO categories (name, type) VALUES (?, ?)",
                        (tx["category"], tx["type"]),
                    ).lastrowid
                else:
                    cat_id = cat["id"]

                dup = find_duplicate(conn, tx["type"], tx["amount"], acc_id, cat_id, tx["date"], tx.get("note"))
                if dup:
                    skipped += 1
                    continue

                cur = conn.execute(
                    """INSERT INTO transactions (type, amount, account_id, category_id, date, note)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (tx["type"], tx["amount"], acc_id, cat_id, tx["date"], tx.get("note")),
                )
                tx_id = cur.lastrowid

                sign = 1 if tx["type"] == "income" else -1
                conn.execute(
                    "UPDATE accounts SET balance = balance + ? WHERE id = ?",
                    (sign * tx["amount"], acc_id),
                )

                for tag_name in tx.get("tags", []):
                    tag_id = _get_or_create_tag(conn, tag_name.strip())
                    conn.execute(
                        "INSERT OR IGNORE INTO transaction_tags (transaction_id, tag_id) VALUES (?, ?)",
                        (tx_id, tag_id),
                    )
                added += 1
            except Exception:
                skipped += 1
    return added, skipped
