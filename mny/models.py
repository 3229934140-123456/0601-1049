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


# ================================
# Projects
# ================================
def list_projects() -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM projects ORDER BY id").fetchall()
        return [_row_to_dict(r) for r in rows]


def get_project(name_or_id: str | int) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        if isinstance(name_or_id, int) or (isinstance(name_or_id, str) and name_or_id.isdigit()):
            row = conn.execute("SELECT * FROM projects WHERE id = ?", (int(name_or_id),)).fetchone()
        else:
            row = conn.execute("SELECT * FROM projects WHERE name = ?", (name_or_id,)).fetchone()
        return _row_to_dict(row)


def add_project(name: str, description: Optional[str] = None) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO projects (name, description) VALUES (?, ?)",
            (name, description),
        )
        return cur.lastrowid


def _get_or_create_project(conn, name: str) -> int:
    row = conn.execute("SELECT id FROM projects WHERE name = ?", (name,)).fetchone()
    if row:
        return row["id"]
    cur = conn.execute("INSERT INTO projects (name) VALUES (?)", (name,))
    return cur.lastrowid


def add_transaction(
    tx_type: str,
    amount: float,
    account: str | int,
    category: str | int,
    tx_date: Optional[str] = None,
    note: Optional[str] = None,
    tags: Optional[List[str]] = None,
    projects: Optional[List[str]] = None,
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
        if projects:
            for p_name in projects:
                p_id = _get_or_create_project(conn, p_name.strip())
                conn.execute(
                    "INSERT OR IGNORE INTO transaction_projects (transaction_id, project_id) VALUES (?, ?)",
                    (tx_id, p_id),
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
    proj_rows = conn.execute(
        """SELECT p.name FROM projects p
           JOIN transaction_projects tp ON p.id = tp.project_id
           WHERE tp.transaction_id = ?""",
        (d["id"],),
    ).fetchall()
    d["projects"] = [r["name"] for r in proj_rows]
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
    project: Optional[str | int] = None,
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
    if project:
        if isinstance(project, int) or (isinstance(project, str) and project.isdigit()):
            sql += " AND EXISTS (SELECT 1 FROM transaction_projects tp WHERE tp.transaction_id = t.id AND tp.project_id = ?)"
            params.append(int(project))
        else:
            sql += " AND EXISTS (SELECT 1 FROM transaction_projects tp JOIN projects p ON tp.project_id = p.id WHERE tp.transaction_id = t.id AND p.name = ?)"
            params.append(project)
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
    projects: Optional[List[str]] = None,
) -> bool:
    existing = get_transaction(tx_id)
    if not existing:
        raise ValueError(f"交易不存在: {tx_id}")

    new_type = tx_type if tx_type else existing["type"]
    new_amount = amount if amount is not None else existing["amount"]
    new_acc_id = get_account(account)["id"] if account else existing["account_id"]

    if tx_type and tx_type != existing["type"]:
        if category is None:
            raise ValueError(
                f"类型从 {existing['type']} 改为 {tx_type} 时必须同时指定同类型的分类（原分类 '{existing['category']}' 是 {existing['type']} 类型）"
            )
    if category:
        cat = get_category(category, new_type)
        if not cat:
            raise ValueError(f"分类 '{category}' 不存在或与类型 {new_type} 不匹配")
        new_cat_id = cat["id"]
    else:
        new_cat_id = existing["category_id"]
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
        if projects is not None:
            conn.execute("DELETE FROM transaction_projects WHERE transaction_id = ?", (tx_id,))
            for p_name in projects:
                p_id = _get_or_create_project(conn, p_name.strip())
                conn.execute(
                    "INSERT OR IGNORE INTO transaction_projects (transaction_id, project_id) VALUES (?, ?)",
                    (tx_id, p_id),
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


def set_budget(scope: str, scope_key: str, year: int, month: int, amount: float) -> int:
    if scope not in ("category", "account", "tag", "project"):
        raise ValueError(f"无效预算维度: {scope}，可选 category/account/tag/project")
    if amount < 0:
        raise ValueError("预算金额不能为负数")
    if scope == "category":
        cat = get_category(scope_key, "expense")
        if not cat:
            raise ValueError(f"支出分类不存在: {scope_key}")
    elif scope == "account":
        acc = get_account(scope_key)
        if not acc:
            raise ValueError(f"账户不存在: {scope_key}")
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO budgets (scope, scope_key, year, month, amount)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(scope, scope_key, year, month) DO UPDATE SET amount=excluded.amount""",
            (scope, scope_key, year, month, amount),
        )
        return cur.lastrowid


def _calc_scope_spent(conn, scope: str, scope_key: str, year: int, month: int) -> float:
    start = f"{year:04d}-{month:02d}-01"
    if month == 12:
        end = f"{year + 1:04d}-01-01"
    else:
        end = f"{year:04d}-{month + 1:02d}-01"
    sql = """
        SELECT COALESCE(SUM(t.amount), 0)
        FROM transactions t
        WHERE t.type = 'expense' AND t.date >= ? AND t.date < ?
    """
    params: list = [start, end]
    if scope == "category":
        sql += " AND EXISTS (SELECT 1 FROM categories c WHERE c.id = t.category_id AND c.name = ?)"
        params.append(scope_key)
    elif scope == "account":
        sql += " AND EXISTS (SELECT 1 FROM accounts a WHERE a.id = t.account_id AND a.name = ?)"
        params.append(scope_key)
    elif scope == "tag":
        sql += """ AND EXISTS (
            SELECT 1 FROM transaction_tags tt
            JOIN tags tg ON tt.tag_id = tg.id
            WHERE tt.transaction_id = t.id AND tg.name = ?
        )"""
        params.append(scope_key)
    elif scope == "project":
        sql += """ AND EXISTS (
            SELECT 1 FROM transaction_projects tp
            JOIN projects p ON tp.project_id = p.id
            WHERE tp.transaction_id = t.id AND p.name = ?
        )"""
        params.append(scope_key)
    return conn.execute(sql, params).fetchone()[0]


def _calc_scope_recurring(conn, scope: str, scope_key: str, year: int, month: int) -> float:
    """计算本月该维度下尚未入账但已到期（pending）的定期支出占用预算的金额"""
    pending = get_pending_recurring(year, month)
    total = 0.0
    for p in pending:
        if p["type"] != "expense":
            continue
        if scope == "category" and p["category"] == scope_key:
            total += p["amount"]
        elif scope == "account" and p["account"] == scope_key:
            total += p["amount"]
        elif scope in ("tag", "project"):
            if scope_key in p.get("tags", []):
                total += p["amount"]
    return total


def list_budgets(year: int, month: int) -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM budgets WHERE year = ? AND month = ?
               ORDER BY scope, scope_key""",
            (year, month),
        ).fetchall()
        results = []
        for r in rows:
            d = _row_to_dict(r)
            d["spent"] = _calc_scope_spent(conn, r["scope"], r["scope_key"], year, month)
            d["remaining"] = r["amount"] - d["spent"]
            d["recurring_pending"] = _calc_scope_recurring(conn, r["scope"], r["scope_key"], year, month)
            d["available"] = d["remaining"] - d["recurring_pending"]
            results.append(d)
        return results


def get_budget_analysis(year: int, month: int) -> Dict[str, Any]:
    """返回本月所有预算的分析：剩余、日均、月底预测、定期占用"""
    today = date.today()
    budgets = list_budgets(year, month)
    _, last_day = calendar.monthrange(year, month)
    days_in_month = last_day
    current_day = min(today.day, last_day) if today.year == year and today.month == month else last_day
    remaining_days = max(days_in_month - current_day, 0)
    results = []
    for b in budgets:
        spent = b["spent"]
        avg = spent / current_day if current_day > 0 else 0
        projected = spent + avg * remaining_days
        will_overrun = projected > b["amount"]
        results.append({
            **b,
            "days_passed": current_day,
            "days_remaining": remaining_days,
            "daily_avg": avg,
            "projected_total": projected,
            "projected_overrun": max(projected - b["amount"], 0),
            "will_overrun": will_overrun,
        })
    return {
        "year": year,
        "month": month,
        "days_passed": current_day,
        "days_remaining": remaining_days,
        "budgets": results,
    }


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
    """返回本月内还未入账的固定收支（从 next_date 起算，已生成的自动排除）"""
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1)
    else:
        end = date(year, month + 1, 1)

    items = list_recurring(active_only=True)
    pending = []
    for r in items:
        try:
            cursor = datetime.strptime(r["next_date"], "%Y-%m-%d").date()
            end_limit = datetime.strptime(r["end_date"], "%Y-%m-%d").date() if r["end_date"] else None
            while cursor < end:
                if (cursor >= start and (end_limit is None or cursor <= end_limit)):
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


# ================================
# Reconcile (对账)
# ================================
def reconcile_transactions(
    bank_records: List[Dict[str, Any]],
    account: str | int,
) -> Dict[str, Any]:
    """
    比对银行/支付平台导出的流水与 mny 内已有的交易。
    bank_records 每条需要至少含: amount, date, [note, category, type]
    返回 { matched, missing_in_mny, missing_in_bank, amount_mismatch }
    """
    acc = get_account(account)
    if not acc:
        raise ValueError(f"账户不存在: {account}")
    acc_id = acc["id"]

    with get_conn() as conn:
        min_date = min((r.get("date") for r in bank_records if r.get("date")), default=None)
        max_date = max((r.get("date") for r in bank_records if r.get("date")), default=None)
        sql = """
            SELECT t.id, t.type, t.amount, t.date, COALESCE(t.note,'') AS note,
                   c.name AS category
            FROM transactions t
            JOIN categories c ON c.id = t.category_id
            WHERE t.account_id = ?
        """
        params: list = [acc_id]
        if min_date:
            sql += " AND t.date >= ?"
            params.append(min_date)
        if max_date:
            sql += " AND t.date <= ?"
            params.append(max_date)
        sql += " ORDER BY t.date, t.id"
        mny_rows = [dict(r) for r in conn.execute(sql, params).fetchall()]

    cleaned_bank: List[Dict[str, Any]] = []
    for rec in bank_records:
        try:
            amount = float(rec.get("amount", 0))
        except (TypeError, ValueError):
            continue
        if amount == 0:
            continue
        if amount < 0:
            tx_type = rec.get("type") or "expense"
            amount = abs(amount)
        else:
            tx_type = rec.get("type") or "income"
        cleaned_bank.append({
            "type": tx_type,
            "amount": amount,
            "date": (rec.get("date") or "").strip() or date.today().isoformat(),
            "note": (rec.get("note") or "").strip(),
            "category": (rec.get("category") or "").strip(),
            "raw": rec,
        })

    def same_as(left: Dict[str, Any], right: Dict[str, Any]) -> bool:
        return (
            left["type"] == right["type"]
            and abs(left["amount"] - right["amount"]) < 0.005
            and left["date"] == right["date"]
            and left.get("note", "") == right.get("note", "")
        )

    used_mny = set()
    used_bank = set()
    matched = []
    amount_mismatch = []

    for i, b in enumerate(cleaned_bank):
        for j, m in enumerate(mny_rows):
            if j in used_mny:
                continue
            if (m["type"] == b["type"] and m["date"] == b["date"]
                    and abs(m["amount"] - b["amount"]) < 0.005
                    and (not b["note"] or m["note"] == b["note"])):
                used_mny.add(j)
                used_bank.add(i)
                matched.append({"mny": m, "bank": b})
                break

    for i, b in enumerate(cleaned_bank):
        if i in used_bank:
            continue
        for j, m in enumerate(mny_rows):
            if j in used_mny:
                continue
            if (m["type"] == b["type"] and m["date"] == b["date"]
                    and (not b["note"] or m["note"] == b["note"])
                    and abs(m["amount"] - b["amount"]) >= 0.005):
                used_mny.add(j)
                used_bank.add(i)
                amount_mismatch.append({"mny": m, "bank": b,
                                        "mny_amount": m["amount"], "bank_amount": b["amount"]})
                break

    missing_in_mny = [cleaned_bank[i] for i in range(len(cleaned_bank)) if i not in used_bank]
    missing_in_bank = [mny_rows[j] for j in range(len(mny_rows)) if j not in used_mny]

    return {
        "account": acc["name"],
        "account_balance": acc["balance"],
        "matched": len(matched),
        "missing_in_mny": missing_in_mny,
        "missing_in_bank": missing_in_bank,
        "amount_mismatch": amount_mismatch,
    }


def apply_reconcile(missing_records: List[Dict[str, Any]],
                    default_category: Optional[str] = None) -> Tuple[int, int, List[str]]:
    """把对账查出 missing_in_mny 的缺失记录补记到 mny"""
    added = 0
    skipped = 0
    errors: List[str] = []
    for rec in missing_records:
        try:
            cat = rec.get("category") or default_category
            if not cat:
                cat = "其他收入" if rec["type"] == "income" else "其他支出"
            add_transaction(
                tx_type=rec["type"],
                amount=rec["amount"],
                account=rec.get("account", "现金"),
                category=cat,
                tx_date=rec.get("date"),
                note=rec.get("note"),
                tags=rec.get("tags"),
                projects=rec.get("projects"),
            )
            added += 1
        except Exception as e:
            skipped += 1
            errors.append(f"{rec.get('date')} {rec.get('amount')}: {e}")
    return added, skipped, errors


# ================================
# Reconcile: balance 余额校准 & 重复识别
# ================================
def find_duplicate_transactions(
    bank_records: List[Dict[str, Any]],
    account: str | int,
) -> Dict[str, Any]:
    """
    分别检测：
    - duplicates_in_bank: 银行流水里自身重复
    - duplicates_in_mny: mny 内部重复
    - duplicates_both: 两边都重复的重复组
    按 (type, date, amount, note) 聚合。
    返回 {duplicates_in_bank, duplicates_in_mny, duplicates_both}
    每一项都是 list of dict: {key, count, items:[记录1, 记录2...]}
    """
    acc = get_account(account)
    if not acc:
        raise ValueError(f"账户不存在: {account}")

    def _group(records: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        buckets: Dict[str, List[Dict[str, Any]]] = {}
        for r in records:
            key = f"{r.get('type')}|{r.get('date')}|{round(float(r.get('amount',0)),2)}|{r.get('note','')}"
            buckets.setdefault(key, []).append(r)
        return buckets

    cleaned_bank: List[Dict[str, Any]] = []
    for rec in bank_records:
        try:
            amount = float(rec.get("amount", 0))
        except (TypeError, ValueError):
            continue
        if amount == 0:
            continue
        if amount < 0:
            tx_type = rec.get("type") or "expense"
            amount = abs(amount)
        else:
            tx_type = rec.get("type") or "income"
        cleaned_bank.append({
            "type": tx_type, "amount": amount,
            "date": (rec.get("date") or "").strip() or date.today().isoformat(),
            "note": (rec.get("note") or "").strip(),
            "category": (rec.get("category") or "").strip(),
            "raw": rec,
        })

    with get_conn() as conn:
        mny_rows = [dict(r) for r in conn.execute(
            """SELECT t.id, t.type, t.amount, t.date, COALESCE(t.note,'') AS note,
                      c.name AS category
               FROM transactions t
               JOIN categories c ON c.id = t.category_id
               WHERE t.account_id = ?
               ORDER BY t.date, t.id""",
            (acc["id"],),
        ).fetchall()]

    bank_groups = _group(cleaned_bank)
    mny_groups = _group(mny_rows)

    dup_in_bank = []
    for k, items in bank_groups.items():
        if len(items) > 1:
            dup_in_bank.append({"key": k, "count": len(items), "items": items})

    dup_in_mny = []
    for k, items in mny_groups.items():
        if len(items) > 1:
            dup_in_mny.append({"key": k, "count": len(items), "items": items})

    dup_both = []
    for k in bank_groups:
        if len(bank_groups[k]) > 1 and len(mny_groups.get(k, [])) > 1:
            dup_both.append({
                "key": k,
                "bank_count": len(bank_groups[k]),
                "mny_count": len(mny_groups[k]),
                "bank_items": bank_groups[k],
                "mny_items": mny_groups[k],
            })

    return {
        "duplicates_in_bank": dup_in_bank,
        "duplicates_in_mny": dup_in_mny,
        "duplicates_both": dup_both,
    }


def delete_duplicate_mny_transaction(tx_id: int) -> bool:
    """删除 mny 中一条重复的交易（同时回滚账户余额）"""
    tx = get_transaction(tx_id)
    if not tx:
        return False
    return delete_transaction(tx_id)


def reconcile_with_balance(
    bank_records: List[Dict[str, Any]],
    account: str | int,
    bank_balance: Optional[float] = None,
) -> Dict[str, Any]:
    """
    在 reconcile_transactions 基础上加上外部余额对比，返回差额和调整建议。
    """
    result = reconcile_transactions(bank_records, account)
    acc = get_account(account)
    result["bank_balance"] = bank_balance
    if bank_balance is not None and acc is not None:
        diff = bank_balance - acc["balance"]
        result["diff"] = diff
        result["diff_abs"] = abs(diff)
    return result


def create_balance_adjustment(
    account: str | int,
    target_balance: float,
    note: Optional[str] = None,
    tx_date: Optional[str] = None,
) -> int:
    """
    生成一条余额校准记录：让 mny 余额对齐到目标余额，
    根据差额作为"其他收入/其他支出"记录一笔。
    """
    acc = get_account(account)
    if not acc:
        raise ValueError(f"账户不存在: {account}")
    diff = target_balance - acc["balance"]
    if abs(diff) < 0.005:
        raise ValueError("账户余额与目标余额一致，无需校准")
    tx_type = "income" if diff > 0 else "expense"
    category = "其他收入" if diff > 0 else "其他支出"
    if not note:
        note = f"余额校准(对账差异)"
    return add_transaction(
        tx_type=tx_type, amount=abs(diff), account=acc["name"],
        category=category, tx_date=tx_date, note=note,
    )


# ================================
# Budget 滚动预算 & 结转
# ================================
def _prev_month(year: int, month: int) -> Tuple[int, int]:
    if month == 1:
        return year - 1, 12
    return year, month - 1


def compute_carry_over(year: int, month: int, scope: str, scope_key: str) -> float:
    """计算上月该维度的结余（正=结转余额，负=超支）"""
    py, pm = _prev_month(year, month)
    prev_budgets = list_budgets(py, pm)
    for b in prev_budgets:
        if b["scope"] == scope and b["scope_key"] == scope_key:
            # 上月 剩余 = 上月预算 - 上月已用
            return b["amount"] - b["spent"]
    return 0.0


def refresh_carry_over(year: int, month: int) -> int:
    """根据上月结余计算本月所有 budget 的 carry_over 字段"""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM budgets WHERE year=? AND month=?",
            (year, month),
        ).fetchall()
        updated = 0
        for r in rows:
            co = compute_carry_over(year, month, r["scope"], r["scope_key"])
            conn.execute(
                "UPDATE budgets SET carry_over=? WHERE id=?",
                (co, r["id"]),
            )
            updated += 1
        return updated


def list_budgets_with_carry(year: int, month: int) -> List[Dict[str, Any]]:
    """含结转版本：本月预算 + 上月结转 = 实际可用"""
    budgets = list_budgets(year, month)
    with get_conn() as conn:
        rows = {r["id"]: r["carry_over"] or 0
                for r in conn.execute(
                    "SELECT id, carry_over FROM budgets WHERE year=? AND month=?",
                    (year, month),
                ).fetchall()}
    results = []
    for b in budgets:
        carry = rows.get(b["id"], 0.0)
        effective_budget = b["amount"] + carry
        results.append({
            **b,
            "carry_over": carry,
            "effective_budget": effective_budget,
            "available_effective": effective_budget - b["spent"] - b["recurring_pending"],
        })
    return results


def get_budget_analysis_with_carry(year: int, month: int) -> Dict[str, Any]:
    today = date.today()
    budgets = list_budgets_with_carry(year, month)
    _, last_day = calendar.monthrange(year, month)
    days_in_month = last_day
    current_day = min(today.day, last_day) if today.year == year and today.month == month else last_day
    remaining_days = max(days_in_month - current_day, 0)
    results = []
    for b in budgets:
        spent = b["spent"]
        avg = spent / current_day if current_day > 0 else 0
        projected = spent + avg * remaining_days
        will_overrun = projected > b["effective_budget"]
        results.append({
            **b,
            "days_passed": current_day,
            "days_remaining": remaining_days,
            "daily_avg": avg,
            "projected_total": projected,
            "projected_overrun": max(projected - b["effective_budget"], 0),
            "will_overrun": will_overrun,
        })
    return {
        "year": year,
        "month": month,
        "days_passed": current_day,
        "days_remaining": remaining_days,
        "budgets": results,
    }


# ================================
# Trend 趋势
# ================================
def _first_day_n_months_ago(n: int) -> date:
    today = date.today()
    m = today.month - n + 1
    y = today.year
    while m <= 0:
        m += 12
        y -= 1
    return date(y, m, 1)


def get_trend(
    months: int = 3,
    scope: str = "category",
    scope_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    最近 N 个月按维度聚合。
    scope ∈ {category, account, tag, project}
    返回 {periods: ["2026-04, 2026-05, 2026-06],
          series: [{name, income:[...], expense:[...]} }
    """
    if scope not in ("category", "account", "tag", "project"):
        raise ValueError(f"无效趋势维度: {scope}")
    start = _first_day_n_months_ago(months)
    end_date = date.today()

    periods = []
    cursor = start
    while (cursor.year, cursor.month) <= (end_date.year, end_date.month):
        periods.append(f"{cursor.year:04d}-{cursor.month:02d}")
        if cursor.month == 12:
            cursor = date(cursor.year + 1, 1, 1)
        else:
            cursor = date(cursor.year, cursor.month + 1, 1)

    period_idx = {p: i for i, p in enumerate(periods)}
    period_income = {p: 0.0 for p in periods}
    period_expense = {p: 0.0 for p in periods}

    with get_conn() as conn:
        sql = f"""
            SELECT t.id, t.type, t.amount, t.date,
        """
        if scope == "category":
            sql += " c.name AS key_name FROM transactions t JOIN categories c ON c.id = t.category_id "
        elif scope == "account":
            sql += " a.name AS key_name FROM transactions t JOIN accounts a ON a.id = t.account_id "
        elif scope == "tag":
            sql += """ tg.name AS key_name FROM transactions t
                       JOIN transaction_tags tt ON tt.transaction_id = t.id
                       JOIN tags tg ON tg.id = tt.tag_id """
        elif scope == "project":
            sql += """ p.name AS key_name FROM transactions t
                       JOIN transaction_projects tp ON tp.transaction_id = t.id
                       JOIN projects p ON p.id = tp.project_id """

        sql += " WHERE t.date >= ? AND t.date < ?"
        params: list = [start.isoformat(), (end_date + timedelta(days=1)).isoformat()]
        if scope_key:
            sql += " AND key_name = ?" if scope in ("category", "account", "tag", "project") else ""
            # 上面不行，scope 用不同的名字，改一下：
        rows = conn.execute(sql.replace(" AND key_name = ?", ""), params).fetchall()

    series_map: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        p = r["date"][:7]
        if p not in period_idx:
            continue
        name = r["key_name"]
        if scope_key and name != scope_key:
            continue
        if name not in series_map:
            series_map[name] = {
                "name": name,
                "income": [0.0] * len(periods),
                "expense": [0.0] * len(periods),
            }
        s = series_map[name]
        if r["type"] == "income":
            s["income"][period_idx[p]] += r["amount"]
            period_income[p] += r["amount"]
        else:
            s["expense"][period_idx[p]] += r["amount"]
            period_expense[p] += r["amount"]

    return {
        "scope": scope,
        "months": months,
        "periods": periods,
        "series": list(series_map.values()),
        "period_income": [period_income[p] for p in periods],
        "period_expense": [period_expense[p] for p in periods],
    }


# ================================
# 净资产快照 Net Worth Snapshots
# ================================
def add_snapshot(date_str: str, account: Optional[str | int],
                 balance: float, liability: float = 0.0,
                 note: Optional[str] = None) -> int:
    """记录某个账户在特定日期的余额/负债快照。account=None 表示整体净资产快照"""
    datetime.strptime(date_str, "%Y-%m-%d")
    account_id = None
    if account is not None:
        acc = get_account(account)
        if not acc:
            raise ValueError(f"账户不存在: {account}")
        account_id = acc["id"]
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO net_worth_snapshots (date, account_id, balance, liability, note)
               VALUES (?, ?, ?, ?, ?)""",
            (date_str, account_id, balance, liability, note),
        )
        return cur.lastrowid


def list_snapshots(months: int = 6,
                   account: Optional[str | int] = None) -> List[Dict[str, Any]]:
    """最近 N 个月的资产快照"""
    start = _first_day_n_months_ago(months)
    with get_conn() as conn:
        sql = """
            SELECT n.id, n.date, n.balance, n.liability, n.note,
                   a.name AS account_name
            FROM net_worth_snapshots n
            LEFT JOIN accounts a ON a.id = n.account_id
            WHERE n.date >= ?
        """
        params: list = [start.isoformat()]
        if account is not None:
            if isinstance(account, int) or (isinstance(account, str) and account.isdigit()):
                sql += " AND n.account_id = ?"
                params.append(int(account))
            else:
                sql += " AND a.name = ?"
                params.append(account)
        sql += " ORDER BY n.date DESC, n.id DESC"
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]


def get_current_net_worth() -> Dict[str, Any]:
    """从 accounts 表实时计算当前净资产（账户余额之和）"""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, name, type, balance FROM accounts ORDER BY id"
        ).fetchall()
        accounts = [dict(r) for r in rows]
        total_assets = sum(a["balance"] for a in accounts)
        # 从快照里读最新整体负债（如有）
        latest_liab = conn.execute(
            "SELECT COALESCE(SUM(liability),0) AS l FROM net_worth_snapshots "
            "WHERE account_id IS NULL ORDER BY date DESC, id DESC LIMIT 1"
        ).fetchone()
        total_liability = latest_liab["l"] if latest_liab else 0.0
    return {
        "accounts": accounts,
        "total_assets": total_assets,
        "total_liability": total_liability,
        "net_worth": total_assets - total_liability,
    }


def get_net_worth_trend(months: int = 6) -> Dict[str, Any]:
    """最近 N 个月净资产趋势：每月取该月所有快照的最后一天"""
    start = _first_day_n_months_ago(months)
    end_date = date.today()

    periods = []
    cursor = start
    while (cursor.year, cursor.month) <= (end_date.year, end_date.month):
        periods.append(f"{cursor.year:04d}-{cursor.month:02d}")
        if cursor.month == 12:
            cursor = date(cursor.year + 1, 1, 1)
        else:
            cursor = date(cursor.year, cursor.month + 1, 1)

    with get_conn() as conn:
        rows = conn.execute(
            """SELECT n.date, n.balance, n.liability, a.name AS account_name
               FROM net_worth_snapshots n
               LEFT JOIN accounts a ON a.id = n.account_id
               WHERE n.date >= ?
               ORDER BY n.date DESC""",
            (start.isoformat(),),
        ).fetchall()

    monthly: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        p = r["date"][:7]
        if p not in periods:
            continue
        if p not in monthly:
            monthly[p] = {"balance": 0.0, "liability": 0.0, "account_snaps": {}}
        key = r["account_name"] or "__total__"
        monthly[p]["account_snaps"][key] = {
            "balance": r["balance"], "liability": r["liability"]
        }

    # 没有快照的月份尝试从 transactions 估算（账户余额累计变化）
    period_idx = {p: i for i, p in enumerate(periods)}
    balances_assets = [None] * len(periods)
    balances_liab = [None] * len(periods)

    # 先填入快照
    for p, v in monthly.items():
        idx = period_idx[p]
        # 如果 __total__ 快照存在，直接用
        if "__total__" in v["account_snaps"]:
            balances_assets[idx] = v["account_snaps"]["__total__"]["balance"]
            balances_liab[idx] = v["account_snaps"]["__total__"]["liability"]
        else:
            # 汇总所有账户快照
            total_bal = sum(a["balance"] for a in v["account_snaps"].values())
            total_liab = sum(a["liability"] for a in v["account_snaps"].values())
            if total_bal > 0 or total_liab > 0:
                balances_assets[idx] = total_bal
                balances_liab[idx] = total_liab

    # 用当前净资产兜底最后一个月
    cur = get_current_net_worth()
    if balances_assets[-1] is None:
        balances_assets[-1] = cur["total_assets"]
    if balances_liab[-1] is None:
        balances_liab[-1] = cur["total_liability"]

    # 向前回溯：某月没快照，用后一月扣掉该月净结余
    for i in range(len(periods) - 2, -1, -1):
        if balances_assets[i] is not None:
            continue
        # 当月（periods[i]）净结余 = 当月收入 - 当月支出
        py, pm = map(int, periods[i].split("-"))
        summary = get_monthly_summary(py, pm)
        net = summary["income"] - summary["expense"]
        # 当月末 = 下月初；下月初资产 = 当月末资产 + 净结余（简化）
        if balances_assets[i + 1] is not None:
            balances_assets[i] = balances_assets[i + 1] - net
            balances_liab[i] = balances_liab[i + 1]

    return {
        "periods": periods,
        "assets": balances_assets,
        "liabilities": balances_liab,
        "net_worth": [(balances_assets[i] or 0) - (balances_liab[i] or 0) if balances_assets[i] is not None else None
                      for i in range(len(periods))],
        "current": cur,
    }


# ================================
# 预算多月连续结转
# ================================
def refresh_carry_over_chain(year: int, month: int) -> int:
    """
    从最早有预算记录的月份开始，链式滚动计算每月 carry_over：
    carry_over(本月) = carry_over(上月) + amount(上月) - spent(上月)
    一直算到指定 (year, month) 前一月为止，再写入本月 budgets 的 carry_over。
    """
    with get_conn() as conn:
        min_row = conn.execute(
            "SELECT MIN(year) AS y, MIN(month) AS m FROM budgets"
        ).fetchone()
        if not min_row or min_row["y"] is None:
            return 0

    # 建立 (y,m) -> set of (scope, scope_key)
    cur_y, cur_m = min_row["y"], min_row["m"]
    # 从 min 月份逐步推到 target 前一月
    target = (year, month)
    updated = 0
    while (cur_y, cur_m) < target:
        # 上月 carry_over = 更早月份累积结余，此处我们只从 min 开始
        ny, nm = (cur_y, cur_m + 1) if cur_m < 12 else (cur_y + 1, 1)
        # 对 (ny, nm) 月的所有 budget 项：carry_over = 上月 (cur_y,cur_m) 的 amount - spent + 上月 carry_over
        # 先找出 (ny, nm) 月有哪些 scope 项
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM budgets WHERE year=? AND month=?", (ny, nm)
            ).fetchall()
            for r in rows:
                # 先看上月这个 scope 项有没有 budget
                prev = conn.execute(
                    "SELECT * FROM budgets WHERE scope=? AND scope_key=? AND year=? AND month=?",
                    (r["scope"], r["scope_key"], cur_y, cur_m),
                ).fetchone()
                chain_co = 0.0
                if prev:
                    prev_co = prev["carry_over"] or 0.0
                    prev_spent = _calc_scope_spent(conn, r["scope"], r["scope_key"], cur_y, cur_m)
                    chain_co = prev_co + prev["amount"] - prev_spent
                # 写入 (ny, nm) 的 carry_over
                conn.execute(
                    "UPDATE budgets SET carry_over=? WHERE id=?",
                    (round(chain_co, 2), r["id"]),
                )
                updated += 1
        cur_y, cur_m = ny, nm
    return updated


# 覆盖旧的 refresh_carry_over，默认走链式
def refresh_carry_over(year: int, month: int) -> int:
    return refresh_carry_over_chain(year, month)


# ================================
# 重复流水识别（三类互斥版）
# ================================
def find_duplicate_transactions_exclusive(
    bank_records: List[Dict[str, Any]],
    account: str | int,
) -> Dict[str, Any]:
    """
    三类互斥：两边都重复的 key 不再出现在银行重复 / mny 重复里。
    """
    full = find_duplicate_transactions(bank_records, account)
    both_keys = {d["key"] for d in full["duplicates_both"]}
    dup_bank = [d for d in full["duplicates_in_bank"] if d["key"] not in both_keys]
    dup_mny = [d for d in full["duplicates_in_mny"] if d["key"] not in both_keys]
    return {
        "duplicates_in_bank": dup_bank,
        "duplicates_in_mny": dup_mny,
        "duplicates_both": full["duplicates_both"],
    }


# ================================
# 年度同比 & 分类结构变化
# ================================
def get_yearly_yoy(year: Optional[int] = None) -> Dict[str, Any]:
    """
    返回指定年份（默认今年）每月 vs 去年同月的收入/支出/净结余同比，
    以及分类结构的同比变化。
    """
    if year is None:
        year = date.today().year
    prev_year = year - 1

    this_year_months = []
    for m in range(1, 13):
        s = get_monthly_summary(year, m)
        this_year_months.append({
            "month": m, "income": s["income"], "expense": s["expense"],
            "net": s["income"] - s["expense"], "by_category": s["by_category"],
        })

    prev_year_months = []
    for m in range(1, 13):
        s = get_monthly_summary(prev_year, m)
        prev_year_months.append({
            "month": m, "income": s["income"], "expense": s["expense"],
            "net": s["income"] - s["expense"], "by_category": s["by_category"],
        })

    yoy_months = []
    for m in range(1, 12 + 1):
        t = this_year_months[m - 1]
        p = prev_year_months[m - 1]
        def _delta(curr, prev):
            if abs(prev) < 0.005:
                return None
            return (curr - prev) / prev * 100
        yoy_months.append({
            "month": m,
            "income": t["income"], "income_prev": p["income"],
            "income_delta": t["income"] - p["income"],
            "income_yoy": _delta(t["income"], p["income"]),
            "expense": t["expense"], "expense_prev": p["expense"],
            "expense_delta": t["expense"] - p["expense"],
            "expense_yoy": _delta(t["expense"], p["expense"]),
            "net": t["net"], "net_prev": p["net"],
            "net_delta": t["net"] - p["net"],
            "net_yoy": _delta(t["net"], p["net"]),
        })

    # 分类结构变化：全年聚合
    def _agg_cats(months_data):
        cats: Dict[str, Dict[str, float]] = {}
        for md in months_data:
            for c in md["by_category"]:
                key = f"{c['type']}:{c['category']}"
                cats.setdefault(key, {"name": c["category"], "type": c["type"], "total": 0.0})
                cats[key]["total"] += c["total"]
        return list(cats.values())

    this_cats = _agg_cats(this_year_months)
    prev_cats = _agg_cats(prev_year_months)
    this_total_income = sum(c["total"] for c in this_cats if c["type"] == "income")
    this_total_expense = sum(c["total"] for c in this_cats if c["type"] == "expense")
    prev_total_income = sum(c["total"] for c in prev_cats if c["type"] == "income")
    prev_total_expense = sum(c["total"] for c in prev_cats if c["type"] == "expense")

    prev_map = {f"{c['type']}:{c['name']}": c for c in prev_cats}
    cat_change = []
    for c in this_cats:
        key = f"{c['type']}:{c['name']}"
        pc = prev_map.get(key, {"total": 0.0})
        total_this = this_total_income if c["type"] == "income" else this_total_expense
        total_prev = prev_total_income if c["type"] == "income" else prev_total_expense
        share_this = (c["total"] / total_this * 100) if total_this > 0 else 0.0
        share_prev = (pc["total"] / total_prev * 100) if total_prev > 0 else 0.0
        cat_change.append({
            "name": c["name"], "type": c["type"],
            "total": c["total"], "total_prev": pc["total"],
            "delta": c["total"] - pc["total"],
            "share": share_this, "share_prev": share_prev,
            "share_delta": share_this - share_prev,
        })
    # 去年有今年没有的分类
    this_map = {f"{c['type']}:{c['name']}": c for c in this_cats}
    for key, pc in prev_map.items():
        if key not in this_map:
            total_prev = prev_total_income if pc["type"] == "income" else prev_total_expense
            share_prev = (pc["total"] / total_prev * 100) if total_prev > 0 else 0.0
            cat_change.append({
                "name": pc["name"], "type": pc["type"],
                "total": 0.0, "total_prev": pc["total"],
                "delta": -pc["total"],
                "share": 0.0, "share_prev": share_prev,
                "share_delta": -share_prev,
            })

    return {
        "year": year, "prev_year": prev_year,
        "months": yoy_months,
        "category_changes": sorted(cat_change, key=lambda x: -abs(x["share_delta"])),
    }


