from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "finance.db"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            type TEXT NOT NULL CHECK(type IN ('income', 'expense')),
            amount REAL NOT NULL,
            category TEXT,
            description TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS goals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            target_amount REAL NOT NULL,
            current_amount REAL NOT NULL DEFAULT 0,
            deadline TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS distribution_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            goal_id INTEGER NOT NULL,
            percentage REAL NOT NULL DEFAULT 0,
            fixed_amount REAL NOT NULL DEFAULT 0,
            rule_type TEXT NOT NULL DEFAULT 'percentage' CHECK(rule_type IN ('percentage', 'fixed')),
            FOREIGN KEY (goal_id) REFERENCES goals(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS goal_contributions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            goal_id INTEGER NOT NULL,
            transaction_id INTEGER,
            amount REAL NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (goal_id) REFERENCES goals(id) ON DELETE CASCADE,
            FOREIGN KEY (transaction_id) REFERENCES transactions(id)
        );
    """)
    conn.commit()
    conn.close()


# --- Transaction helpers ---

def add_transaction(user_id: int, tx_type: str, amount: float,
                    category: str | None = None, description: str | None = None) -> int:
    conn = get_connection()
    cur = conn.execute(
        "INSERT INTO transactions (user_id, type, amount, category, description) VALUES (?, ?, ?, ?, ?)",
        (user_id, tx_type, amount, category, description),
    )
    tx_id = cur.lastrowid
    conn.commit()
    conn.close()
    return tx_id


def get_monthly_summary(user_id: int, year: int, month: int) -> dict:
    conn = get_connection()
    rows = conn.execute(
        """SELECT type, category, SUM(amount) as total
           FROM transactions
           WHERE user_id = ? AND strftime('%Y', created_at) = ? AND strftime('%m', created_at) = ?
           GROUP BY type, category
           ORDER BY type, total DESC""",
        (user_id, str(year), f"{month:02d}"),
    ).fetchall()
    conn.close()

    income_total = 0.0
    expense_total = 0.0
    income_by_cat: dict[str, float] = {}
    expense_by_cat: dict[str, float] = {}

    for row in rows:
        cat = row["category"] or "Uncategorized"
        if row["type"] == "income":
            income_total += row["total"]
            income_by_cat[cat] = row["total"]
        else:
            expense_total += row["total"]
            expense_by_cat[cat] = row["total"]

    return {
        "income_total": income_total,
        "expense_total": expense_total,
        "income_by_category": income_by_cat,
        "expense_by_category": expense_by_cat,
        "net": income_total - expense_total,
    }


def get_recent_transactions(user_id: int, limit: int = 10) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM transactions WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# --- Goal helpers ---

def add_goal(user_id: int, name: str, target_amount: float,
             deadline: str | None = None) -> int:
    conn = get_connection()
    cur = conn.execute(
        "INSERT INTO goals (user_id, name, target_amount, deadline) VALUES (?, ?, ?, ?)",
        (user_id, name, target_amount, deadline),
    )
    goal_id = cur.lastrowid
    conn.commit()
    conn.close()
    return goal_id


def get_goals(user_id: int) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM goals WHERE user_id = ? ORDER BY created_at", (user_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def contribute_to_goal(user_id: int, goal_id: int, amount: float,
                       transaction_id: int | None = None):
    conn = get_connection()
    conn.execute(
        "UPDATE goals SET current_amount = current_amount + ? WHERE id = ? AND user_id = ?",
        (amount, goal_id, user_id),
    )
    conn.execute(
        "INSERT INTO goal_contributions (user_id, goal_id, transaction_id, amount) VALUES (?, ?, ?, ?)",
        (user_id, goal_id, transaction_id, amount),
    )
    conn.commit()
    conn.close()


def delete_goal(user_id: int, goal_id: int) -> bool:
    conn = get_connection()
    cur = conn.execute(
        "DELETE FROM goals WHERE id = ? AND user_id = ?", (goal_id, user_id)
    )
    deleted = cur.rowcount > 0
    conn.commit()
    conn.close()
    return deleted


# --- Distribution rule helpers ---

def set_distribution_rules(user_id: int, rules: list[tuple[int, str, float]]):
    """rules is a list of (goal_id, rule_type, value) tuples. Replaces all existing rules."""
    conn = get_connection()
    conn.execute("DELETE FROM distribution_rules WHERE user_id = ?", (user_id,))
    for goal_id, rule_type, value in rules:
        if rule_type == "fixed":
            conn.execute(
                "INSERT INTO distribution_rules (user_id, goal_id, fixed_amount, rule_type) VALUES (?, ?, ?, 'fixed')",
                (user_id, goal_id, value),
            )
        else:
            conn.execute(
                "INSERT INTO distribution_rules (user_id, goal_id, percentage, rule_type) VALUES (?, ?, ?, 'percentage')",
                (user_id, goal_id, value),
            )
    conn.commit()
    conn.close()


def get_distribution_rules(user_id: int) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        """SELECT dr.goal_id, dr.percentage, dr.fixed_amount, dr.rule_type, g.name as goal_name
           FROM distribution_rules dr
           JOIN goals g ON g.id = dr.goal_id
           WHERE dr.user_id = ?""",
        (user_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_monthly_contributions(user_id: int, year: int, month: int) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        """SELECT g.name as goal_name, SUM(gc.amount) as total
           FROM goal_contributions gc
           JOIN goals g ON g.id = gc.goal_id
           WHERE gc.user_id = ? AND strftime('%Y', gc.created_at) = ? AND strftime('%m', gc.created_at) = ?
           GROUP BY gc.goal_id
           ORDER BY total DESC""",
        (user_id, str(year), f"{month:02d}"),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def distribute_income(user_id: int, amount: float, transaction_id: int) -> list[dict]:
    """Distribute income across goals based on saved rules.
    Fixed amounts are deducted first, then percentages apply to the remainder."""
    rules = get_distribution_rules(user_id)
    if not rules:
        return []

    allocations = []
    remaining = amount

    # Fixed amounts first
    for rule in rules:
        if rule["rule_type"] != "fixed":
            continue
        alloc_amount = min(round(rule["fixed_amount"], 2), remaining)
        if alloc_amount > 0:
            contribute_to_goal(user_id, rule["goal_id"], alloc_amount, transaction_id)
            allocations.append({
                "goal_name": rule["goal_name"],
                "amount": alloc_amount,
                "label": f"{rule['fixed_amount']:,.2f} fixed",
            })
            remaining -= alloc_amount

    # Percentages on the remainder
    for rule in rules:
        if rule["rule_type"] != "percentage":
            continue
        alloc_amount = round(remaining * rule["percentage"] / 100, 2)
        if alloc_amount > 0:
            contribute_to_goal(user_id, rule["goal_id"], alloc_amount, transaction_id)
            allocations.append({
                "goal_name": rule["goal_name"],
                "amount": alloc_amount,
                "label": f"{rule['percentage']}%",
            })

    return allocations
