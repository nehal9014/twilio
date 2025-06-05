import logging
import re
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    filters
)
from twilio.rest import Client
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

user_sessions = {}
ASK_CREDENTIALS = 0

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome! Please send your Twilio AccountSID and AuthToken in the following format:\n\nACxxxxxxxxxxxxxxxx your_token"
    )
    return ASK_CREDENTIALS

async def receive_credentials(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    parts = text.split()

    if len(parts) != 2:
        await update.message.reply_text("⚠️ Please send your credentials like: ACxxxxxxxxxxxxxxxx your_token")
        return ASK_CREDENTIALS

    sid, token = parts

    try:
        client = Client(sid, token)
        client.api.accounts(sid).fetch()

        user_sessions[update.effective_user.id] = {
            'sid': sid,
            'token': token,
            'client': client
        }

        await update.message.reply_text(
            "✅ Login successful!\n\nUse /buy <area_code> to search for Canadian numbers. Example: /buy 825"
        )
        return ConversationHandler.END

    except Exception as e:
        await update.message.reply_text(f"❌ Login failed. Try /start again. Error: {e}")
        return ASK_CREDENTIALS

async def buy_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    session = user_sessions.get(user_id)

    if not session:
        await update.message.reply_text("❌ Please login first using /start")
        return

    if not context.args:
        await update.message.reply_text("⚠️ Usage: /buy <area_code>")
        return

    area_code = context.args[0]
    client = session['client']

    try:
        if not area_code.isdigit() or len(area_code) != 3:
            await update.message.reply_text("⚠️ Please enter a valid 3-digit area code.")
            return

        numbers = client.available_phone_numbers('CA').local.list(
            area_code=int(area_code),
            sms_enabled=True,
            limit=30
        )

        if not numbers:
            await update.message.reply_text("❌ No matching numbers found.")
            return

        keyboard = []
        for num in numbers:
            keyboard.append([
                InlineKeyboardButton(f"{num.phone_number}", callback_data=f"COPY:{num.phone_number}"),
                InlineKeyboardButton("Buy", callback_data=f"BUY:{num.phone_number}")
            ])

        await update.message.reply_text(
            "📱 Available Canadian Numbers:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    session = user_sessions.get(user_id)

    if not session:
        await query.edit_message_text("❌ Please login first using /start")
        return

    client = session['client']
    data = query.data

    if data.startswith("BUY:"):
        phone_number = data.split("BUY:")[1]
        try:
            number = client.incoming_phone_numbers.create(phone_number=phone_number)
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("Show Messages", callback_data=f"SMS:{number.sid}"),
                    InlineKeyboardButton("Delete", callback_data=f"DEL:{number.sid}")
                ]
            ])
            text = f"✅ Number {number.phone_number} purchased successfully!"
            await query.edit_message_text(text, reply_markup=keyboard)
        except Exception as e:
            await query.edit_message_text(f"❌ Purchase failed. Error: {e}")

    elif data.startswith("DEL:"):
        sid = data.split("DEL:")[1]
        try:
            client.incoming_phone_numbers(sid).delete()
            await query.edit_message_text("✅ Number deleted successfully.")
        except Exception as e:
            await query.edit_message_text(f"❌ Deletion failed: {e}")

    elif data.startswith("SMS:"):
        sid = data.split("SMS:")[1]
        try:
            number_obj = client.incoming_phone_numbers(sid).fetch()
            messages = client.messages.list(to=number_obj.phone_number, limit=5)
            if not messages:
                await query.edit_message_text("No recent messages received.")
                return
            text = "Recent Messages:\n"
            for msg in messages:
                text += f"From: {msg.from_}\nText: {msg.body}\n---\n"
            await query.edit_message_text(text)
        except Exception as e:
            await query.edit_message_text(f"❌ Failed to fetch messages: {e}")

if __name__ == '__main__':
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={ASK_CREDENTIALS: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_credentials)]},
        fallbacks=[],
    )

    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("buy", buy_number))
    application.add_handler(CallbackQueryHandler(handle_callback))

    application.run_polling()
