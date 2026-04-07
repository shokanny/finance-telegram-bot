import os
import logging

from dotenv import load_dotenv
from telegram import Update, BotCommand
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

import database as db
from handlers.transactions import get_transaction_handlers
from handlers.goals import get_goal_handlers

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

HELP_TEXT = """
Finance Bot - Track your money and goals

TRANSACTIONS:
  /income [amount] [category] - Record income
  /expense [amount] [category] - Record expense
  /summary [year month] - Monthly summary
  /history [count] - Recent transactions

GOALS:
  /addgoal - Create a savings goal
  /goals - View all goals with progress
  /fund [goal_id amount] - Add money to a goal
  /deletegoal <goal_id> - Remove a goal
  /distribute - Set auto-distribution rules

OTHER:
  /help - Show this message
  /cancel - Cancel current operation
""".strip()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"Hey {update.effective_user.first_name}! "
        "I'm your personal finance bot.\n\n"
        "I help you track income & expenses, set savings goals, "
        "and auto-distribute earnings across your goals.\n\n"
        "Start with:\n"
        "  /addgoal - to set your first savings goal\n"
        "  /income - to log earnings\n"
        "  /expense - to log spending\n\n"
        "Type /help for all commands."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_TEXT)


async def post_init(application):
    await application.bot.set_my_commands([
        BotCommand("start", "Start the bot"),
        BotCommand("help", "Show all commands"),
        BotCommand("income", "Record income"),
        BotCommand("expense", "Record expense"),
        BotCommand("summary", "Monthly summary"),
        BotCommand("history", "Recent transactions"),
        BotCommand("addgoal", "Create a savings goal"),
        BotCommand("goals", "View goals with progress"),
        BotCommand("fund", "Add money to a goal"),
        BotCommand("distribute", "Set auto-distribution rules"),
        BotCommand("deletegoal", "Remove a goal"),
    ])


def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN not set. Copy .env.example to .env and add your token.")

    db.init_db()

    app = ApplicationBuilder().token(token).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))

    for handler in get_transaction_handlers():
        app.add_handler(handler)

    for handler in get_goal_handlers():
        app.add_handler(handler)

    logger.info("Bot starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
