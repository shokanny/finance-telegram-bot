from __future__ import annotations

from datetime import datetime

from telegram import Update
from telegram.ext import (
    ContextTypes, CommandHandler, ConversationHandler, MessageHandler, filters,
)

import database as db

# Conversation states for /addgoal
GOAL_NAME, GOAL_AMOUNT, GOAL_DEADLINE = range(3)
# Conversation states for /distribute
DIST_INPUT = 0
# Conversation states for /fund
FUND_GOAL, FUND_AMOUNT = range(2)


# --- Add Goal ---

async def addgoal_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start adding a goal. Usage: /addgoal"""
    await update.message.reply_text("What's the name of your goal? (e.g. Emergency Fund)")
    return GOAL_NAME


async def goal_name_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["goal_name"] = update.message.text.strip()
    await update.message.reply_text("What's the target amount in HKD?")
    return GOAL_AMOUNT


async def goal_amount_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("Please enter a valid number.")
        return GOAL_AMOUNT

    if amount <= 0:
        await update.message.reply_text("Amount must be positive.")
        return GOAL_AMOUNT

    context.user_data["goal_target"] = amount
    await update.message.reply_text(
        "Deadline? Enter a date (YYYY-MM-DD) or /skip for no deadline."
    )
    return GOAL_DEADLINE


async def goal_deadline_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    try:
        datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        await update.message.reply_text("Invalid date format. Use YYYY-MM-DD or /skip.")
        return GOAL_DEADLINE

    return await _save_goal(update, context, text)


async def goal_skip_deadline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await _save_goal(update, context, None)


async def _save_goal(update: Update, context: ContextTypes.DEFAULT_TYPE,
                     deadline: str | None):
    user_id = update.effective_user.id
    name = context.user_data["goal_name"]
    target = context.user_data["goal_target"]

    db.add_goal(user_id, name, target, deadline)

    msg = f"Goal created: {name}\n  Target: {target:,.2f} HKD"
    if deadline:
        msg += f"\n  Deadline: {deadline}"

    await update.message.reply_text(msg)
    return ConversationHandler.END


async def goal_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Cancelled.")
    return ConversationHandler.END


# --- List Goals / Status ---

async def goals_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show all goals with progress. Usage: /goals"""
    user_id = update.effective_user.id
    goals = db.get_goals(user_id)

    if not goals:
        await update.message.reply_text("No goals yet. Use /addgoal to create one.")
        return

    lines = ["Your Goals:\n"]
    for g in goals:
        pct = (g["current_amount"] / g["target_amount"] * 100) if g["target_amount"] > 0 else 0
        bar_filled = int(pct / 5)
        bar = "█" * bar_filled + "░" * (20 - bar_filled)

        line = f"{g['id']}. {g['name']}\n"
        line += f"   [{bar}] {pct:.1f}%\n"
        line += f"   {g['current_amount']:,.2f} / {g['target_amount']:,.2f} HKD"
        if g["deadline"]:
            line += f"\n   Deadline: {g['deadline']}"
        lines.append(line)

    await update.message.reply_text("\n\n".join(lines))


async def deletegoal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delete a goal. Usage: /deletegoal 1"""
    if not context.args:
        await update.message.reply_text("Usage: /deletegoal <goal_id>\nUse /goals to see IDs.")
        return

    try:
        goal_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Invalid goal ID.")
        return

    user_id = update.effective_user.id
    if db.delete_goal(user_id, goal_id):
        await update.message.reply_text(f"Goal #{goal_id} deleted.")
    else:
        await update.message.reply_text("Goal not found.")


# --- Fund a Goal Manually ---

async def fund_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manually add money to a goal. Usage: /fund or /fund 1 5000"""
    if context.args and len(context.args) >= 2:
        try:
            goal_id = int(context.args[0])
            amount = float(context.args[1])
        except ValueError:
            await update.message.reply_text("Usage: /fund <goal_id> <amount>")
            return ConversationHandler.END
        return await _do_fund(update, context, goal_id, amount)

    user_id = update.effective_user.id
    goals = db.get_goals(user_id)
    if not goals:
        await update.message.reply_text("No goals yet. Use /addgoal to create one.")
        return ConversationHandler.END

    lines = ["Which goal? Enter the ID:\n"]
    for g in goals:
        lines.append(f"  {g['id']}. {g['name']} ({g['current_amount']:,.2f}/{g['target_amount']:,.2f})")
    await update.message.reply_text("\n".join(lines))
    return FUND_GOAL


async def fund_goal_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        context.user_data["fund_goal_id"] = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("Please enter a valid goal ID.")
        return FUND_GOAL
    await update.message.reply_text("How much to add?")
    return FUND_AMOUNT


async def fund_amount_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("Please enter a valid number.")
        return FUND_AMOUNT

    goal_id = context.user_data["fund_goal_id"]
    return await _do_fund(update, context, goal_id, amount)


async def _do_fund(update: Update, context: ContextTypes.DEFAULT_TYPE,
                   goal_id: int, amount: float):
    user_id = update.effective_user.id
    db.contribute_to_goal(user_id, goal_id, amount)

    goals = db.get_goals(user_id)
    goal = next((g for g in goals if g["id"] == goal_id), None)
    if goal:
        pct = goal["current_amount"] / goal["target_amount"] * 100
        await update.message.reply_text(
            f"Added {amount:,.2f} HKD to {goal['name']}\n"
            f"Progress: {goal['current_amount']:,.2f} / {goal['target_amount']:,.2f} ({pct:.1f}%)"
        )
    else:
        await update.message.reply_text("Goal not found.")
    return ConversationHandler.END


# --- Distribution Rules ---

async def distribute_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set auto-distribution rules. Usage: /distribute"""
    user_id = update.effective_user.id
    goals = db.get_goals(user_id)

    if not goals:
        await update.message.reply_text("No goals yet. Use /addgoal first.")
        return ConversationHandler.END

    current_rules = db.get_distribution_rules(user_id)

    lines = ["Set how income is auto-distributed to goals.\n"]
    lines.append("Your goals:")
    for g in goals:
        lines.append(f"  {g['id']}. {g['name']}")

    if current_rules:
        lines.append("\nCurrent rules:")
        for r in current_rules:
            lines.append(f"  {r['goal_name']}: {r['percentage']}%")

    lines.append("\nEnter rules as: goal_id percentage")
    lines.append("One per line, then send /done")
    lines.append("Example:\n  1 50\n  2 20\n  3 10")
    lines.append("\nTotal can be up to 100%. The rest stays as free spending.")

    context.user_data["dist_rules"] = []
    await update.message.reply_text("\n".join(lines))
    return DIST_INPUT


async def distribute_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    parts = text.split()
    if len(parts) != 2:
        await update.message.reply_text("Format: goal_id percentage (e.g. '1 50')")
        return DIST_INPUT

    try:
        goal_id = int(parts[0])
        pct = float(parts[1])
    except ValueError:
        await update.message.reply_text("Invalid input. Use: goal_id percentage")
        return DIST_INPUT

    if pct <= 0 or pct > 100:
        await update.message.reply_text("Percentage must be between 0 and 100.")
        return DIST_INPUT

    context.user_data["dist_rules"].append((goal_id, pct))
    await update.message.reply_text(f"Added: goal #{goal_id} = {pct}%. Send more or /done")
    return DIST_INPUT


async def distribute_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    rules = context.user_data.get("dist_rules", [])

    if not rules:
        await update.message.reply_text("No rules set. Cancelled.")
        return ConversationHandler.END

    total_pct = sum(pct for _, pct in rules)
    if total_pct > 100:
        await update.message.reply_text(
            f"Total is {total_pct}% which exceeds 100%. Please start over with /distribute"
        )
        return ConversationHandler.END

    db.set_distribution_rules(user_id, rules)

    goals = db.get_goals(user_id)
    goal_map = {g["id"]: g["name"] for g in goals}

    lines = ["Distribution rules saved:\n"]
    for goal_id, pct in rules:
        name = goal_map.get(goal_id, f"#{goal_id}")
        lines.append(f"  {name}: {pct}%")
    lines.append(f"  Free spending: {100 - total_pct}%")
    lines.append("\nIncome will be auto-distributed when you use /income")

    await update.message.reply_text("\n".join(lines))
    return ConversationHandler.END


def get_goal_handlers() -> list:
    addgoal_conv = ConversationHandler(
        entry_points=[CommandHandler("addgoal", addgoal_start)],
        states={
            GOAL_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, goal_name_received)],
            GOAL_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, goal_amount_received)],
            GOAL_DEADLINE: [
                CommandHandler("skip", goal_skip_deadline),
                MessageHandler(filters.TEXT & ~filters.COMMAND, goal_deadline_received),
            ],
        },
        fallbacks=[CommandHandler("cancel", goal_cancel)],
    )

    fund_conv = ConversationHandler(
        entry_points=[CommandHandler("fund", fund_start)],
        states={
            FUND_GOAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, fund_goal_received)],
            FUND_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, fund_amount_received)],
        },
        fallbacks=[CommandHandler("cancel", goal_cancel)],
    )

    distribute_conv = ConversationHandler(
        entry_points=[CommandHandler("distribute", distribute_start)],
        states={
            DIST_INPUT: [
                CommandHandler("done", distribute_done),
                MessageHandler(filters.TEXT & ~filters.COMMAND, distribute_input),
            ],
        },
        fallbacks=[CommandHandler("cancel", goal_cancel)],
    )

    return [
        addgoal_conv,
        fund_conv,
        distribute_conv,
        CommandHandler("goals", goals_list),
        CommandHandler("deletegoal", deletegoal),
    ]
