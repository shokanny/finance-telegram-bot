from __future__ import annotations

from datetime import datetime

from telegram import Update
from telegram.ext import ContextTypes, CommandHandler, ConversationHandler, MessageHandler, filters

import database as db

# Conversation states
AMOUNT, CATEGORY, DESCRIPTION = range(3)

EXPENSE_CATEGORIES = [
    "Food", "Transport", "Housing", "Entertainment",
    "Shopping", "Health", "Education", "Bills", "Other",
]

INCOME_CATEGORIES = [
    "Salary", "Freelance", "Investment", "Gift", "Refund", "Other",
]


async def income_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start income logging. Usage: /income or /income 20000"""
    args = context.args
    if args and len(args) >= 1:
        try:
            amount = float(args[0])
        except ValueError:
            await update.message.reply_text("Invalid amount. Usage: /income 20000")
            return ConversationHandler.END

        category = " ".join(args[1:]) if len(args) > 1 else None
        return await _save_income(update, context, amount, category)

    context.user_data["tx_type"] = "income"
    await update.message.reply_text("How much did you earn? (enter amount)")
    return AMOUNT


async def expense_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start expense logging. Usage: /expense or /expense 150 Food"""
    args = context.args
    if args and len(args) >= 1:
        try:
            amount = float(args[0])
        except ValueError:
            await update.message.reply_text("Invalid amount. Usage: /expense 150 Food")
            return ConversationHandler.END

        category = " ".join(args[1:]) if len(args) > 1 else None
        return await _save_expense(update, context, amount, category)

    context.user_data["tx_type"] = "expense"
    await update.message.reply_text("How much did you spend? (enter amount)")
    return AMOUNT


async def amount_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("Please enter a valid number.")
        return AMOUNT

    if amount <= 0:
        await update.message.reply_text("Amount must be positive.")
        return AMOUNT

    context.user_data["amount"] = amount
    tx_type = context.user_data["tx_type"]
    cats = INCOME_CATEGORIES if tx_type == "income" else EXPENSE_CATEGORIES
    cat_list = "\n".join(f"  {c}" for c in cats)
    await update.message.reply_text(
        f"Category? Type one or pick from:\n{cat_list}\n\nOr /skip to skip."
    )
    return CATEGORY


async def category_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["category"] = update.message.text.strip()
    tx_type = context.user_data["tx_type"]
    amount = context.user_data["amount"]
    category = context.user_data["category"]

    if tx_type == "income":
        return await _save_income(update, context, amount, category)
    else:
        return await _save_expense(update, context, amount, category)


async def skip_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tx_type = context.user_data["tx_type"]
    amount = context.user_data["amount"]

    if tx_type == "income":
        return await _save_income(update, context, amount, None)
    else:
        return await _save_expense(update, context, amount, None)


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Cancelled.")
    return ConversationHandler.END


async def _save_income(update: Update, context: ContextTypes.DEFAULT_TYPE,
                       amount: float, category: str | None):
    user_id = update.effective_user.id
    tx_id = db.add_transaction(user_id, "income", amount, category)

    # Auto-distribute if rules exist
    allocations = db.distribute_income(user_id, amount, tx_id)

    msg = f"Income recorded: +{amount:,.2f} HKD"
    if category:
        msg += f" ({category})"

    if allocations:
        msg += "\n\nAuto-distributed to goals:"
        for a in allocations:
            msg += f"\n  {a['goal_name']}: +{a['amount']:,.2f} ({a['percentage']}%)"
        total_alloc = sum(a["amount"] for a in allocations)
        free = amount - total_alloc
        msg += f"\n  Free spending: {free:,.2f}"

    await update.message.reply_text(msg)
    return ConversationHandler.END


async def _save_expense(update: Update, context: ContextTypes.DEFAULT_TYPE,
                        amount: float, category: str | None):
    user_id = update.effective_user.id
    db.add_transaction(user_id, "expense", amount, category)

    msg = f"Expense recorded: -{amount:,.2f} HKD"
    if category:
        msg += f" ({category})"

    await update.message.reply_text(msg)
    return ConversationHandler.END


async def summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show monthly summary. Usage: /summary or /summary 2026 4"""
    user_id = update.effective_user.id
    now = datetime.now()
    year, month = now.year, now.month

    if context.args and len(context.args) == 2:
        try:
            year, month = int(context.args[0]), int(context.args[1])
        except ValueError:
            await update.message.reply_text("Usage: /summary or /summary 2026 4")
            return

    data = db.get_monthly_summary(user_id, year, month)

    if data["income_total"] == 0 and data["expense_total"] == 0:
        await update.message.reply_text(f"No transactions for {year}-{month:02d}.")
        return

    lines = [f"Summary for {year}-{month:02d}\n"]

    if data["income_by_category"]:
        lines.append("INCOME:")
        for cat, amt in data["income_by_category"].items():
            lines.append(f"  {cat}: +{amt:,.2f}")
        lines.append(f"  Total: +{data['income_total']:,.2f}\n")

    if data["expense_by_category"]:
        lines.append("EXPENSES:")
        for cat, amt in data["expense_by_category"].items():
            lines.append(f"  {cat}: -{amt:,.2f}")
        lines.append(f"  Total: -{data['expense_total']:,.2f}\n")

    lines.append(f"NET: {data['net']:+,.2f} HKD")

    await update.message.reply_text("\n".join(lines))


async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show recent transactions. Usage: /history or /history 20"""
    user_id = update.effective_user.id
    limit = 10
    if context.args:
        try:
            limit = int(context.args[0])
        except ValueError:
            pass

    txs = db.get_recent_transactions(user_id, limit)
    if not txs:
        await update.message.reply_text("No transactions yet.")
        return

    lines = ["Recent transactions:\n"]
    for tx in txs:
        sign = "+" if tx["type"] == "income" else "-"
        cat = f" ({tx['category']})" if tx["category"] else ""
        date = tx["created_at"][:10]
        lines.append(f"  {date} {sign}{tx['amount']:,.2f}{cat}")

    await update.message.reply_text("\n".join(lines))


def get_transaction_handlers() -> list:
    income_conv = ConversationHandler(
        entry_points=[CommandHandler("income", income_start)],
        states={
            AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, amount_received)],
            CATEGORY: [
                CommandHandler("skip", skip_category),
                MessageHandler(filters.TEXT & ~filters.COMMAND, category_received),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    expense_conv = ConversationHandler(
        entry_points=[CommandHandler("expense", expense_start)],
        states={
            AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, amount_received)],
            CATEGORY: [
                CommandHandler("skip", skip_category),
                MessageHandler(filters.TEXT & ~filters.COMMAND, category_received),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    return [
        income_conv,
        expense_conv,
        CommandHandler("summary", summary),
        CommandHandler("history", history),
    ]
