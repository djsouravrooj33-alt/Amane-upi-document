import os
import re
import asyncio
import requests
from flask import Flask, request
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# ========= ENV =========
BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "8145485145"))
ALLOWED_GROUP = int(os.getenv("ALLOWED_GROUP", "-1003296016362"))

# ========= APPS =========
app = Flask(__name__)

tg_app = (
    Application
    .builder()
    .token(BOT_TOKEN)
    .updater(None)          # ✅ webhook-only mode
    .build()
)

# ========= AUTH =========
def is_authorized(update: Update) -> bool:
    user = update.effective_user
    chat = update.effective_chat

    if user and user.id == OWNER_ID:
        return True
    if chat and chat.id == ALLOWED_GROUP:
        return True
    return False

# ========= UPI DATA =========
UPI_REGEX = re.compile(r"^[\w.\-]{2,256}@[a-zA-Z]{2,64}$")

UPI_BANK_IFSC = {
    "oksbi": ("State Bank of India", "SBIN0000001"),
    "okhdfcbank": ("HDFC Bank", "HDFC0000001"),
    "okicici": ("ICICI Bank", "ICIC0000001"),
    "okaxis": ("Axis Bank", "UTIB0000001"),
    "ybl": ("Yes Bank", "YESB0000001"),
    "paytm": ("Paytm Payments Bank", "PYTM0000001"),
}

# ========= IFSC LOOKUP =========
def get_ifsc_info(ifsc: str):
    r = requests.get(f"https://ifsc.razorpay.com/{ifsc}", timeout=10)
    if r.status_code != 200:
        return None
    return r.json()

# ========= COMMAND =========
async def upi_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return

    if not context.args:
        await update.message.reply_text("❌ Usage: /upi name@bank")
        return

    upi = context.args[0].lower()

    if not UPI_REGEX.match(upi):
        await update.message.reply_text("❌ Invalid UPI format")
        return

    handle = upi.split("@")[1]
    if handle not in UPI_BANK_IFSC:
        await update.message.reply_text("⚠️ Unknown UPI handle")
        return

    bank, ifsc = UPI_BANK_IFSC[handle]
    info = get_ifsc_info(ifsc)

    if not info:
        await update.message.reply_text(
            f"🔎 UPI: {upi}\n🏦 Bank: {bank}\n🏧 IFSC: {ifsc}"
        )
        return

    await update.message.reply_text(
        f"🔎 UPI: `{upi}`\n"
        f"🏦 Bank: {bank}\n"
        f"🏧 IFSC: {ifsc}\n"
        f"🏢 Branch: {info['BRANCH']}\n"
        f"📍 City: {info['CITY']}\n"
        f"🗺 State: {info['STATE']}",
        parse_mode="Markdown"
    )

# ========= FLASK WEBHOOK =========
@app.route("/", methods=["POST"])
def webhook():
    data = request.get_json(force=True)
    update = Update.de_json(data, tg_app.bot)
    tg_app.update_queue.put_nowait(update)
    return "OK"

@app.route("/", methods=["GET"])
def health():
    return "Bot running"

# ========= STARTUP =========
async def startup():
    tg_app.add_handler(CommandHandler("upi", upi_cmd))

    # ✅ Clean previous webhook
    await tg_app.bot.delete_webhook(drop_pending_updates=True)

    webhook_url = os.environ.get("RENDER_EXTERNAL_URL")
    if webhook_url:
        await tg_app.bot.set_webhook(webhook_url)

# ========= MAIN =========
if __name__ == "__main__":
    asyncio.run(startup())
    PORT = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=PORT)