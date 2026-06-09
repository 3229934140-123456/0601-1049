from datetime import datetime, date, timedelta
from pathlib import Path
import shutil
import calendar
import csv
import json
import re
from typing import Optional, List, Dict, Any, Tuple, Callable
from .db import get_conn, DB_PATH


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


# ================================
# Transfer (账户转账)
# ================================
def add_transfer(from_account: str | int, to_account: str | int, amount: float,
                 tx_date: Optional[str] = None, note: Optional[str] = None) -> int:
    if amount <= 0:
        raise ValueError("转账金额必须为正数")
    from_acc = get_account(from_account)
    to_acc = get_account(to_account)
    if not from_acc:
        raise ValueError(f"转出账户不存在: {from_account}")
    if not to_acc:
        raise ValueError(f"转入账户不存在: {to_account}")
    if from_acc["id"] == to_acc["id"]:
        raise ValueError("转出和转入账户不能相同")
    if tx_date is None:
        tx_date = date.today().isoformat()
    else:
        datetime.strptime(tx_date, "%Y-%m-%d")

    with get_conn() as conn:
        conn.execute("UPDATE accounts SET balance = balance - ? WHERE id = ?", (amount, from_acc["id"]))
        conn.execute("UPDATE accounts SET balance = balance + ? WHERE id = ?", (amount, to_acc["id"]))
        cur = conn.execute(
            "INSERT INTO transfers (from_account_id, to_account_id, amount, date, note) VALUES (?, ?, ?, ?, ?)",
            (from_acc["id"], to_acc["id"], amount, tx_date, note),
        )
        return cur.lastrowid


def list_transfers(start_date: Optional[str] = None, end_date: Optional[str] = None,
                   account: Optional[str | int] = None) -> List[Dict[str, Any]]:
    sql = "SELECT tf.* FROM transfers tf WHERE 1=1"
    params = []
    if start_date:
        sql += " AND tf.date >= ?"
        params.append(start_date)
    if end_date:
        sql += " AND tf.date <= ?"
        params.append(end_date)
    if account:
        acc = get_account(account)
        if acc:
            sql += " AND (tf.from_account_id = ? OR tf.to_account_id = ?)"
            params.extend([acc["id"], acc["id"]])
    sql += " ORDER BY tf.date DESC, tf.id DESC"
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
        results = []
        for r in rows:
            d = _row_to_dict(r)
            d["from_account"] = conn.execute("SELECT name FROM accounts WHERE id = ?", (d["from_account_id"],)).fetchone()["name"]
            d["to_account"] = conn.execute("SELECT name FROM accounts WHERE id = ?", (d["to_account_id"],)).fetchone()["name"]
            results.append(d)
        return results


def delete_transfer(transfer_id: int) -> bool:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM transfers WHERE id = ?", (transfer_id,)).fetchone()
        if not row:
            raise ValueError(f"转账记录不存在: {transfer_id}")
        conn.execute("UPDATE accounts SET balance = balance + ? WHERE id = ?", (row["amount"], row["from_account_id"]))
        conn.execute("UPDATE accounts SET balance = balance - ? WHERE id = ?", (row["amount"], row["to_account_id"]))
        conn.execute("DELETE FROM transfers WHERE id = ?", (transfer_id,))
        return True


def get_account_transfer_stats(account_id: int) -> Dict[str, float]:
    with get_conn() as conn:
        transfer_in = conn.execute(
            "SELECT COALESCE(SUM(amount),0) FROM transfers WHERE to_account_id = ?", (account_id,)
        ).fetchone()[0]
        transfer_out = conn.execute(
            "SELECT COALESCE(SUM(amount),0) FROM transfers WHERE from_account_id = ?", (account_id,)
        ).fetchone()[0]
        return {"transfer_in": transfer_in, "transfer_out": transfer_out}


# ================================
# Recurring (定期记账)
# ================================
def _calc_next_date(current: str, frequency: str, interval_day: Optional[int] = None) -> str:
    d = datetime.strptime(current, "%Y-%m-%d").date()
    if frequency == "daily":
        return (d + timedelta(days=1)).isoformat()
    elif frequency == "weekly":
        return (d + timedelta(days=7)).isoformat()
    elif frequency == "monthly":
        day = interval_day if interval_day else d.day
        year = d.year
        month = d.month + 1
        if month > 12:
            month = 1
            year += 1
        last_day = calendar.monthrange(year, month)[1]
        day = min(day, last_day)
        return date(year, month, day).isoformat()
    elif frequency == "yearly":
        day = interval_day if interval_day else d.day
        month = d.month
        year = d.year + 1
        last_day = calendar.monthrange(year, month)[1]
        day = min(day, last_day)
        return date(year, month, day).isoformat()
    return d.isoformat()


def add_recurring(tx_type: str, amount: float, account: str | int, category: str | int,
                  frequency: str, interval_day: Optional[int] = None,
                  start_date: Optional[str] = None, end_date: Optional[str] = None,
                  note: Optional[str] = None, tags: Optional[List[str]] = None) -> int:
    if amount <= 0:
        raise ValueError("金额必须为正数")
    if frequency not in ("daily", "weekly", "monthly", "yearly"):
        raise ValueError(f"无效频率: {frequency}")
    acc = get_account(account)
    if not acc:
        raise ValueError(f"账户不存在: {account}")
    cat = get_category(category, tx_type)
    if not cat:
        raise ValueError(f"分类不存在或类型不匹配: {category}")

    today = date.today().isoformat()
    if start_date is None:
        start_date = today
    else:
        datetime.strptime(start_date, "%Y-%m-%d")
    if end_date:
        datetime.strptime(end_date, "%Y-%m-%d")
        if end_date < start_date:
            raise ValueError("结束日期不能早于开始日期")

    if frequency == "monthly":
        if interval_day is None:
            interval_day = datetime.strptime(start_date, "%Y-%m-%d").day
        if not (1 <= interval_day <= 31):
            raise ValueError("月周期的 interval_day 需在 1-31")
    elif frequency == "weekly":
        if interval_day is None:
            interval_day = datetime.strptime(start_date, "%Y-%m-%d").weekday() + 1
        if not (1 <= interval_day <= 7):
            raise ValueError("周周期的 interval_day 需在 1-7")
    elif frequency == "yearly":
        if interval_day is None:
            interval_day = datetime.strptime(start_date, "%Y-%m-%d").day
        if not (1 <= interval_day <= 31):
            raise ValueError("年周期的 interval_day 需在 1-31")

    next_date = start_date
    tags_str = ",".join([t.strip() for t in tags]) if tags else None

    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO recurring (type, amount, account_id, category_id, frequency, interval_day,
               start_date, end_date, next_date, note, tags)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (tx_type, amount, acc["id"], cat["id"], frequency, interval_day,
             start_date, end_date, next_date, note, tags_str),
        )
        return cur.lastrowid


def list_recurring(active_only: bool = True) -> List[Dict[str, Any]]:
    with get_conn() as conn:
        sql = "SELECT * FROM recurring"
        if active_only:
            sql += " WHERE active = 1"
        sql += " ORDER BY next_date ASC, id ASC"
        rows = conn.execute(sql).fetchall()
        results = []
        for r in rows:
            d = _row_to_dict(r)
            d["account"] = conn.execute("SELECT name FROM accounts WHERE id = ?", (d["account_id"],)).fetchone()["name"]
            d["category"] = conn.execute("SELECT name FROM categories WHERE id = ?", (d["category_id"],)).fetchone()["name"]
            d["tags"] = [t for t in (d.get("tags") or "").split(",") if t]
            results.append(d)
        return results


def get_pending_recurring(year: int, month: int) -> List[Dict[str, Any]]:
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1)
    else:
        end = date(year, month + 1, 1)
    today = date.today().isoformat()

    items = list_recurring(active_only=True)
    pending = []
    for r in items:
        try:
            cursor = datetime.strptime(r["start_date"], "%Y-%m-%d").date()
            end_limit = datetime.strptime(r["end_date"], "%Y-%m-%d").date() if r["end_date"] else None
            while cursor < end:
                if (cursor >= start and (end_limit is None or cursor <= end_limit)
                        and cursor.isoformat() >= today):
                    pending.append({
                        "id": r["id"],
                        "type": r["type"],
                        "amount": r["amount"],
                        "account": r["account"],
                        "category": r["category"],
                        "date": cursor.isoformat(),
                        "note": r.get("note"),
                        "tags": r.get("tags", []),
                        "frequency": r["frequency"],
                    })
                cursor = datetime.strptime(
                    _calc_next_date(cursor.isoformat(), r["frequency"], r.get("interval_day")),
                    "%Y-%m-%d"
                ).date()
                if cursor < start:
                    continue
                if cursor >= date(2200, 1, 1):
                    break
        except Exception:
            continue
    pending.sort(key=lambda x: x["date"])
    return pending


def generate_recurring(today: Optional[str] = None) -> List[int]:
    if today is None:
        today = date.today().isoformat()
    generated_ids: List[int] = []
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM recurring WHERE active = 1 AND next_date <= ?",
            (today,),
        ).fetchall()
        for r in rows:
            try:
                end_limit = r["end_date"]
                next_d = r["next_date"]
                while next_d <= today and (end_limit is None or next_d <= end_limit):
                    tags_list = [t for t in (r["tags"] or "").split(",") if t]
                    cur = conn.execute(
                        """INSERT INTO transactions (type, amount, account_id, category_id, date, note)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (r["type"], r["amount"], r["account_id"], r["category_id"], next_d, r["note"]),
                    )
                    tx_id = cur.lastrowid
                    sign = 1 if r["type"] == "income" else -1
                    conn.execute(
                        "UPDATE accounts SET balance = balance + ? WHERE id = ?",
                        (sign * r["amount"], r["account_id"]),
                    )
                    for tag_name in tags_list:
                        tag_id = _get_or_create_tag(conn, tag_name.strip())
                        conn.execute(
                            "INSERT OR IGNORE INTO transaction_tags (transaction_id, tag_id) VALUES (?, ?)",
                            (tx_id, tag_id),
                        )
                    generated_ids.append(tx_id)

                    last_generated = next_d
                    next_d = _calc_next_date(next_d, r["frequency"], r["interval_day"])
                    conn.execute(
                        "UPDATE recurring SET last_generated = ?, next_date = ? WHERE id = ?",
                        (last_generated, next_d, r["id"]),
                    )
                    if r["end_date"] and next_d > r["end_date"]:
                        conn.execute("UPDATE recurring SET active = 0 WHERE id = ?", (r["id"],))
                        break
            except Exception:
                continue
    return generated_ids


def confirm_recurring(recurring_id: int, tx_date: Optional[str] = None) -> int:
    with get_conn() as conn:
        r = conn.execute("SELECT * FROM recurring WHERE id = ? AND active = 1", (recurring_id,)).fetchone()
        if not r:
            raise ValueError(f"定期记账不存在或已停用: {recurring_id}")
        if tx_date is None:
            tx_date = r["next_date"]
        else:
            datetime.strptime(tx_date, "%Y-%m-%d")

        tags_list = [t for t in (r["tags"] or "").split(",") if t]
        cur = conn.execute(
            """INSERT INTO transactions (type, amount, account_id, category_id, date, note)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (r["type"], r["amount"], r["account_id"], r["category_id"], tx_date, r["note"]),
        )
        tx_id = cur.lastrowid
        sign = 1 if r["type"] == "income" else -1
        conn.execute(
            "UPDATE accounts SET balance = balance + ? WHERE id = ?",
            (sign * r["amount"], r["account_id"]),
        )
        for tag_name in tags_list:
            tag_id = _get_or_create_tag(conn, tag_name.strip())
            conn.execute(
                "INSERT OR IGNORE INTO transaction_tags (transaction_id, tag_id) VALUES (?, ?)",
                (tx_id, tag_id),
            )
        next_d = _calc_next_date(tx_date, r["frequency"], r["interval_day"])
        conn.execute(
            "UPDATE recurring SET last_generated = ?, next_date = ? WHERE id = ?",
            (tx_date, next_d, r["id"]),
        )
        if r["end_date"] and next_d > r["end_date"]:
            conn.execute("UPDATE recurring SET active = 0 WHERE id = ?", (r["id"],))
        return tx_id


def delete_recurring(recurring_id: int) -> bool:
    with get_conn() as conn:
        row = conn.execute("SELECT id FROM recurring WHERE id = ?", (recurring_id,)).fetchone()
        if not row:
            raise ValueError(f"定期记账不存在: {recurring_id}")
        conn.execute("DELETE FROM recurring WHERE id = ?", (recurring_id,))
        return True


def toggle_recurring(recurring_id: int, active: Optional[bool] = None) -> bool:
    with get_conn() as conn:
        row = conn.execute("SELECT active FROM recurring WHERE id = ?", (recurring_id,)).fetchone()
        if not row:
            raise ValueError(f"定期记账不存在: {recurring_id}")
        new_active = (1 - row["active"]) if active is None else (1 if active else 0)
        conn.execute("UPDATE recurring SET active = ? WHERE id = ?", (new_active, recurring_id))
        return True


# ================================
# Export (导出)
# ================================
def export_transactions_csv(filepath: str, txs: List[Dict[str, Any]]):
    with open(filepath, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "date", "type", "amount", "account", "category", "tags", "note"])
        for tx in txs:
            writer.writerow([
                tx["id"], tx["date"], tx["type"], tx["amount"], tx["account"],
                tx["category"], ",".join(tx.get("tags", [])), tx.get("note") or "",
            ])


def export_transactions_json(filepath: str, txs: List[Dict[str, Any]]):
    clean = []
    for tx in txs:
        clean.append({k: v for k, v in tx.items() if k not in ("account_id", "category_id")})
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(clean, f, ensure_ascii=False, indent=2)


def export_transfers_csv(filepath: str, transfers: List[Dict[str, Any]]):
    with open(filepath, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "date", "from_account", "to_account", "amount", "note"])
        for t in transfers:
            writer.writerow([
                t["id"], t["date"], t["from_account"], t["to_account"], t["amount"], t.get("note") or "",
            ])


def export_report_json(filepath: str, data: Dict[str, Any]):
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)


def export_report_csv(filepath: str, data: Dict[str, Any]):
    with open(filepath, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        for k, v in data.items():
            if isinstance(v, list):
                writer.writerow([f"[{k}]"])
                if v:
                    headers = list(v[0].keys())
                    writer.writerow(headers)
                    for row in v:
                        writer.writerow([row.get(h, "") for h in headers])
            else:
                writer.writerow([k, v])


# ================================
# Backup (备份/恢复)
# ================================
def backup_database(target_dir: Optional[str] = None) -> str:
    db_path = Path(DB_PATH)
    if target_dir:
        target = Path(target_dir)
    else:
        target = db_path.parent / "backups"
    target.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = target / f"finance_backup_{timestamp}.db"
    shutil.copy2(db_path, backup_path)
    return str(backup_path)


def list_backups(backup_dir: Optional[str] = None) -> List[Dict[str, Any]]:
    if backup_dir:
        target = Path(backup_dir)
    else:
        target = Path(DB_PATH).parent / "backups"
    if not target.exists():
        return []
    backups = []
    for f in target.glob("finance_backup_*.db"):
        stat = f.stat()
        backups.append({
            "file": str(f),
            "name": f.name,
            "size": stat.st_size,
            "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        })
    backups.sort(key=lambda x: x["modified"], reverse=True)
    return backups


def restore_database(backup_file: str) -> bool:
    src = Path(backup_file)
    if not src.exists():
        raise ValueError(f"备份文件不存在: {backup_file}")
    dst = Path(DB_PATH)
    if dst.exists():
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        auto_backup = dst.parent / f"finance_pre_restore_{timestamp}.db"
        shutil.copy2(dst, auto_backup)
    shutil.copy2(src, dst)
    return True


# ================================
# Improved Import (改进导入)
# ================================
def validate_import_record(rec: Dict[str, Any]) -> Tuple[bool, str, Dict[str, Any]]:
    cleaned = dict(rec)
    tx_type = (cleaned.get("type") or "").strip().lower()
    if tx_type not in ("income", "expense"):
        return False, f"无效交易类型: {tx_type}", cleaned
    try:
        amount = float(cleaned.get("amount", 0))
    except (TypeError, ValueError):
        return False, f"金额无法解析: {cleaned.get('amount')}", cleaned
    if amount < 0:
        return False, f"金额不能为负数: {amount}", cleaned
    if amount == 0:
        return False, f"金额不能为零", cleaned
    cleaned["amount"] = amount
    cleaned["type"] = tx_type

    account = (cleaned.get("account") or "现金").strip()
    category = (cleaned.get("category") or "").strip()
    if not category:
        category = "其他收入" if tx_type == "income" else "其他支出"
    cleaned["account"] = account
    cleaned["category"] = category

    tx_date = (cleaned.get("date") or "").strip()
    if not tx_date:
        tx_date = date.today().isoformat()
    try:
        datetime.strptime(tx_date, "%Y-%m-%d")
    except ValueError:
        return False, f"日期格式错误: {tx_date}", cleaned
    cleaned["date"] = tx_date

    note = (cleaned.get("note") or "").strip() or None
    cleaned["note"] = note

    tags_raw = cleaned.get("tags")
    if isinstance(tags_raw, str):
        tags = [t.strip() for t in tags_raw.split(",") if t.strip()]
    elif isinstance(tags_raw, list):
        tags = [str(t).strip() for t in tags_raw if str(t).strip()]
    else:
        tags = []
    cleaned["tags"] = tags
    return True, "", cleaned


def bulk_import_v2(
    transactions: List[Dict[str, Any]],
    on_category_mismatch: Optional[Callable[[Dict[str, Any], str, List[Dict[str, Any]]], Optional[str]]] = None,
) -> Tuple[int, int, List[Tuple[int, str]]]:
    added = 0
    skipped = 0
    errors: List[Tuple[int, str]] = []
    with get_conn() as conn:
        for idx, raw_tx in enumerate(transactions):
            try:
                ok, msg, tx = validate_import_record(raw_tx)
                if not ok:
                    skipped += 1
                    errors.append((idx, msg))
                    continue

                acc = conn.execute("SELECT * FROM accounts WHERE name = ?", (tx["account"],)).fetchone()
                if not acc:
                    cur = conn.execute(
                        "INSERT INTO accounts (name, type, balance) VALUES (?, ?, 0)",
                        (tx["account"], "cash"),
                    )
                    acc_id = cur.lastrowid
                else:
                    acc_id = acc["id"]

                cat = conn.execute(
                    "SELECT * FROM categories WHERE name = ? AND type = ?",
                    (tx["category"], tx["type"]),
                ).fetchone()
                if not cat:
                    same_name = conn.execute(
                        "SELECT * FROM categories WHERE name = ?", (tx["category"],)
                    ).fetchone()
                    if same_name and same_name["type"] != tx["type"]:
                        alt_cats = conn.execute(
                            "SELECT * FROM categories WHERE type = ? ORDER BY name",
                            (tx["type"],),
                        ).fetchall()
                        alt_cats_dicts = [_row_to_dict(c) for c in alt_cats]
                        new_cat_name = None
                        if on_category_mismatch:
                            new_cat_name = on_category_mismatch(tx, same_name["type"], alt_cats_dicts)
                        if not new_cat_name:
                            skipped += 1
                            errors.append((idx, f"分类 '{tx['category']}' 是 {same_name['type']} 类型，与交易类型 {tx['type']} 不匹配，且未提供替代分类"))
                            continue
                        selected = conn.execute(
                            "SELECT * FROM categories WHERE name = ? AND type = ?",
                            (new_cat_name, tx["type"]),
                        ).fetchone()
                        if selected:
                            cat_id = selected["id"]
                        else:
                            cur = conn.execute(
                                "INSERT INTO categories (name, type) VALUES (?, ?)",
                                (new_cat_name, tx["type"]),
                            )
                            cat_id = cur.lastrowid
                    else:
                        cur = conn.execute(
                            "INSERT INTO categories (name, type) VALUES (?, ?)",
                            (tx["category"], tx["type"]),
                        )
                        cat_id = cur.lastrowid
                else:
                    cat_id = cat["id"]

                dup = conn.execute(
                    """SELECT id FROM transactions
                       WHERE type=? AND amount=? AND account_id=? AND category_id=? AND date=? AND COALESCE(note,'')=?""",
                    (tx["type"], tx["amount"], acc_id, cat_id, tx["date"], tx["note"] or ""),
                ).fetchone()
                if dup:
                    skipped += 1
                    continue

                cur = conn.execute(
                    """INSERT INTO transactions (type, amount, account_id, category_id, date, note)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (tx["type"], tx["amount"], acc_id, cat_id, tx["date"], tx["note"]),
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
            except Exception as e:
                skipped += 1
                errors.append((idx, f"处理异常: {e}"))
    return added, skipped, errors
