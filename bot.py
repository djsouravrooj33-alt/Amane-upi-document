import os
import re
import json
import aiohttp
from flask import Flask
from threading import Thread

from telegram import Update, ParseMode
from telegram.ext import (
    Updater,
    CommandHandler,
    CallbackContext,
    Dispatcher
)

# ================= CONFIG =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN not set!")

GROUP_ID = -1003296016362
OWNER_ID = 8145485145
API_BY = "@amane_friends"

AUTH_FILE = "authorized_users.json"

# ================= KEEP ALIVE =================
app_web = Flask(__name__)

@app_web.route("/")
def home():
    return "Bot is alive"

def keep_alive():
    Thread(
        target=lambda: app_web.run(
            host="0.0.0.0",
            port=int(os.environ.get("PORT", 8080))
        ),
        daemon=True
    ).start()

# ================= AUTH SYSTEM =================
def load_users():
    if os.path.exists(AUTH_FILE):
        try:
            with open(AUTH_FILE) as f:
                return set(json.load(f))
        except:
            return set()
    return set()

def save_users(users):
    with open(AUTH_FILE, "w") as f:
        json.dump(list(users), f)

AUTHORIZED_USERS = load_users()

def is_authorized(update: Update) -> bool:
    uid = update.effective_user.id
    return uid == OWNER_ID or uid in AUTHORIZED_USERS

# ================= GROUP ONLY =================
def group_only(update: Update) -> bool:
    chat = update.effective_chat
    return chat and chat.id == GROUP_ID

# ================= UPI VALIDATION =================
UPI_REGEX = re.compile(r"^[a-z0-9.\-_]{2,256}@[a-z]{2,64}$")

def is_valid_upi(upi_id: str) -> bool:
    return bool(UPI_REGEX.match(upi_id))

# ================= LOCAL BANK MAP =================
UPI_BANK_MAP = {
    "ybl":    {"app": "PhonePe", "ifsc": "YESB0UPI"},
    "okaxis": {"app": "Google Pay (Axis)", "ifsc": "UTIB0UPI"},
    "oksbi":  {"app": "Google Pay (SBI)", "ifsc": "SBIN0UPI"},
    "okhdfcbank": {"app": "Google Pay (HDFC)", "ifsc": "HDFC0UPI"},
    "paytm":  {"app": "Paytm", "ifsc": "PYTM0123456"},
    "apl":    {"app": "Amazon Pay", "ifsc": "ABCD0APUPI"},
    "upi":    {"app": "BHIM UPI", "ifsc": "NPCI0000001"}
}

# ================= FALLBACK UPI API =================
async def fallback_upi_lookup(bankcode: str):
    url = f"https://upi-bank-api.vercel.app/{bankcode}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=5) as r:
                if r.status == 200:
                    return await r.json()
    except:
        pass
    return None

# ================= IFSC API =================
async def fetch_ifsc_info(code: str):
    try:
        url = f"https://ifsc.razorpay.com/{code}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=8) as response:
                if response.status == 200:
                    return await response.json()
    except:
        pass
    return None

# ================= COMMANDS =================
def start(update: Update, context: CallbackContext):
    if not group_only(update):
        return
    if not is_authorized(update):
        update.message.reply_text("❌ You are not authorized")
        return
    
    update.message.reply_text(
        "🤖 *Bot Ready!*\n\n"
        "💳 `/upi username@bank` - UPI info\n"
        "🏦 `/ifsc SBIN0001234` - IFSC info\n\n"
        "👑 *Owner Commands:*\n"
        "`/adduser ID` - Add user\n"
        "`/removeuser ID` - Remove user\n"
        "`/listusers` - List users\n\n"
        f"⚡ API BY {API_BY}",
        parse_mode=ParseMode.MARKDOWN
    )

# ---------- OWNER COMMANDS ----------
def adduser(update: Update, context: CallbackContext):
    if update.effective_user.id != OWNER_ID:
        return
    if not context.args:
        update.message.reply_text("Usage: /adduser 123456789")
        return
    try:
        uid = int(context.args[0])
        AUTHORIZED_USERS.add(uid)
        save_users(AUTHORIZED_USERS)
        update.message.reply_text(f"✅ Added `{uid}`", parse_mode=ParseMode.MARKDOWN)
    except:
        update.message.reply_text("❌ Invalid ID")

def removeuser(update: Update, context: CallbackContext):
    if update.effective_user.id != OWNER_ID:
        return
    if not context.args:
        update.message.reply_text("Usage: /removeuser 123456789")
        return
    try:
        uid = int(context.args[0])
        AUTHORIZED_USERS.discard(uid)
        save_users(AUTHORIZED_USERS)
        update.message.reply_text(f"❌ Removed `{uid}`", parse_mode=ParseMode.MARKDOWN)
    except:
        update.message.reply_text("❌ Invalid ID")

def listusers(update: Update, context: CallbackContext):
    if update.effective_user.id != OWNER_ID:
        return
    if not AUTHORIZED_USERS:
        update.message.reply_text("📭 No authorized users")
        return
    text = "\n".join([f"• `{uid}`" for uid in AUTHORIZED_USERS])
    update.message.reply_text(
        f"📋 *Authorized Users:*\n{text}",
        parse_mode=ParseMode.MARKDOWN
    )

# ---------- UPI COMMAND ----------
def upi(update: Update, context: CallbackContext):
    if not group_only(update):
        return
    if not is_authorized(update):
        update.message.reply_text("❌ Not authorized")
        return

    if not context.args:
        update.message.reply_text("Usage: /upi username@bank")
        return

    upi_id = context.args[0].lower()

    if not is_valid_upi(upi_id):
        update.message.reply_text("❌ Invalid UPI format")
        return

    _, bankcode = upi_id.split("@", 1)

    app_name = "Unknown"
    ifsc_code = "N/A"
    source = "Local"

    if bankcode in UPI_BANK_MAP:
        app_name = UPI_BANK_MAP[bankcode]["app"]
        ifsc_code = UPI_BANK_MAP[bankcode]["ifsc"]
    else:
        # Async call synchronously
        import asyncio
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            data = loop.run_until_complete(fallback_upi_lookup(bankcode))
            loop.close()
            if data:
                app_name = data.get("bank", "Unknown")
                ifsc_code = data.get("ifsc", "N/A")
                source = "API"
        except:
            pass

    update.message.reply_text(
        "💳 *UPI DETAILS*\n"
        "━━━━━━━━━━━━━━━━\n"
        f"📌 `{upi_id}`\n"
        f"🏦 `{app_name}`\n"
        f"🏷 IFSC: `{ifsc_code}`\n"
        f"🔍 Source: `{source}`\n"
        "━━━━━━━━━━━━━━━━\n"
        f"⚡ {API_BY}",
        parse_mode=ParseMode.MARKDOWN
    )

# ---------- IFSC COMMAND ----------
def ifsc(update: Update, context: CallbackContext):
    if not group_only(update):
        return
    if not is_authorized(update):
        update.message.reply_text("❌ Not authorized")
        return
    
    if not context.args:
        update.message.reply_text("Usage: /ifsc SBIN0001234")
        return
    
    code = context.args[0].upper()
    msg = update.message.reply_text("🔄 Fetching IFSC...")
    
    # Async call synchronously
    import asyncio
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        data = loop.run_until_complete(fetch_ifsc_info(code))
        loop.close()
    except:
        data = None
    
    if not data:
        msg.edit_text("❌ Invalid IFSC Code")
        return
    
    text = (
        "✅ *IFSC FOUND*\n"
        "━━━━━━━━━━━━━━━━\n"
        f"🏦 *Bank:* `{data.get('BANK', 'N/A')}`\n"
        f"📍 *Branch:* `{data.get('BRANCH', 'N/A')}`\n"
        f"🏙️ *City:* `{data.get('CITY', 'N/A')}`\n"
        f"🌍 *State:* `{data.get('STATE', 'N/A')}`\n"
        "━━━━━━━━━━━━━━━━\n"
        f"⚡ {API_BY}"
    )
    
    msg.edit_text(text, parse_mode=ParseMode.MARKDOWN)

# ================= MAIN =================
def main():
    keep_alive()
    
    # Updater ব্যবহার করে 13.15 ভার্সন
    updater = Updater(token=BOT_TOKEN, use_context=True)
    dp = updater.dispatcher
    
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("upi", upi))
    dp.add_handler(CommandHandler("ifsc", ifsc))
    dp.add_handler(CommandHandler("adduser", adduser))
    dp.add_handler(CommandHandler("removeuser", removeuser))
    dp.add_handler(CommandHandler("listusers", listusers))
    
    print("✅ Bot Started with PTB 13.15")
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()