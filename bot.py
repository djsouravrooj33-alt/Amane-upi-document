import os
import re
import json
import aiohttp
from flask import Flask
from threading import Thread

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes
)

# ================= CONFIG =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN not set!")

GROUP_ID = -1003296016362
OWNER_ID = 8145485145
CHANNEL_USERNAME = "@amane_friends"
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
async def group_only(update: Update) -> bool:
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
    """Fetch IFSC info from dual API sources"""
    
    # Try primary API (datayuge)
    try:
        url = f"https://ifsc.datayuge.com/?code={code}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=8) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get('status') and data.get('data'):
                        return {'source': 'datayuge', 'data': data['data']}
    except:
        pass
    
    # Try backup API (razorpay)
    try:
        url = f"https://ifsc.razorpay.com/{code}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=8) as response:
                if response.status == 200:
                    data = await response.json()
                    return {'source': 'razorpay', 'data': data}
    except:
        pass
    
    return None

# ================= COMMANDS =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await group_only(update):
        return
    if not is_authorized(update):
        await update.message.reply_text("❌ You are not authorized")
        return
    
    await update.message.reply_text(
        "🤖 *Bot Ready!*\n\n"
        "💳 `/upi username@bank` - UPI info\n"
        "🏦 `/ifsc SBIN0001234` - IFSC info\n\n"
        "👑 Owner commands:\n"
        "`/adduser ID` - Add user\n"
        "`/removeuser ID` - Remove user\n"
        "`/listusers` - List users\n\n"
        f"⚡ API BY {API_BY}",
        parse_mode="Markdown"
    )

# ---------- OWNER COMMANDS ----------
async def adduser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    uid = int(context.args[0])
    AUTHORIZED_USERS.add(uid)
    save_users(AUTHORIZED_USERS)
    await update.message.reply_text(f"✅ Added `{uid}`", parse_mode="Markdown")

async def removeuser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    uid = int(context.args[0])
    AUTHORIZED_USERS.discard(uid)
    save_users(AUTHORIZED_USERS)
    await update.message.reply_text(f"❌ Removed `{uid}`", parse_mode="Markdown")

async def listusers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    text = "\n".join(map(str, AUTHORIZED_USERS)) or "No users"
    await update.message.reply_text(text)

# ---------- UPI COMMAND ----------
async def upi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await group_only(update):
        return
    if not is_authorized(update):
        await update.message.reply_text("❌ Not authorized")
        return

    if not context.args:
        await update.message.reply_text("Usage: /upi username@bank")
        return

    upi_id = context.args[0].lower()

    if not is_valid_upi(upi_id):
        await update.message.reply_text("❌ Invalid UPI format")
        return

    _, bankcode = upi_id.split("@", 1)

    app_name = "Unknown"
    ifsc_code = "Not available"
    source = "Local map"

    if bankcode in UPI_BANK_MAP:
        app_name = UPI_BANK_MAP[bankcode]["app"]
        ifsc_code = UPI_BANK_MAP[bankcode]["ifsc"]
    else:
        data = await fallback_upi_lookup(bankcode)
        if data:
            app_name = data.get("bank", "Unknown Bank")
            ifsc_code = data.get("ifsc", "Not available")
            source = "API fallback"

    await update.message.reply_text(
        "💳 *UPI ANALYSIS*\n"
        "━━━━━━━━━━━━━━━━\n"
        f"📌 UPI ID: `{upi_id}`\n"
        f"🏦 Bank/App: `{app_name}`\n"
        f"🏷 IFSC: `{ifsc_code}`\n"
        f"🔍 Source: `{source}`\n"
        "━━━━━━━━━━━━━━━━\n"
        "⚠️ NPCI rule: Owner name not public\n"
        f"⚡ API BY {API_BY}",
        parse_mode="Markdown"
    )

# ---------- IFSC COMMAND ----------
async def ifsc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """IFSC code info command - Dual API"""
    if not await group_only(update):
        return
    if not is_authorized(update):
        await update.message.reply_text("❌ Not authorized")
        return
    
    if not context.args:
        await update.message.reply_text(
            "🏦 *Usage:* `/ifsc SBIN0001234`",
            parse_mode="Markdown"
        )
        return
    
    code = context.args[0].upper()
    msg = await update.message.reply_text(
        "🔄 *Fetching IFSC information...*",
        parse_mode="Markdown"
    )
    
    result = await fetch_ifsc_info(code)
    
    if not result:
        await msg.edit_text(
            "❌ *Invalid IFSC Code or API Error!*",
            parse_mode="Markdown"
        )
        return
    
    # Format response based on source
    if result['source'] == 'datayuge':
        d = result['data']
        text = (
            "✅ *IFSC INFORMATION*\n"
            "━━━━━━━━━━━━━━━━\n"
            f"🏦 *Bank:* `{d.get('bank', 'N/A')}`\n"
            f"📍 *Branch:* `{d.get('branch', 'N/A')}`\n"
            f"🏙️ *City:* `{d.get('city', 'N/A')}`\n"
            f"🏛️ *District:* `{d.get('district', 'N/A')}`\n"
            f"🌍 *State:* `{d.get('state', 'N/A')}`\n"
            f"📮 *Address:* `{d.get('address', 'N/A')[:100]}...`\n"
            "━━━━━━━━━━━━━━━━\n"
            f"⚡ API BY {API_BY}"
        )
    else:
        d = result['data']
        text = (
            "✅ *IFSC INFORMATION*\n"
            "━━━━━━━━━━━━━━━━\n"
            f"🏦 *Bank:* `{d.get('BANK', 'N/A')}`\n"
            f"📍 *Branch:* `{d.get('BRANCH', 'N/A')}`\n"
            f"🏙️ *City:* `{d.get('CITY', 'N/A')}`\n"
            f"🏛️ *District:* `{d.get('DISTRICT', 'N/A')}`\n"
            f"🌍 *State:* `{d.get('STATE', 'N/A')}`\n"
            f"📮 *Address:* `{d.get('ADDRESS', 'N/A')[:100]}...`\n"
            "━━━━━━━━━━━━━━━━\n"
            f"⚡ API BY {API_BY}"
        )
    
    await msg.edit_text(text, parse_mode="Markdown")

# ================= MAIN =================
def main():
    keep_alive()
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("upi", upi))
    app.add_handler(CommandHandler("ifsc", ifsc))
    app.add_handler(CommandHandler("adduser", adduser))
    app.add_handler(CommandHandler("removeuser", removeuser))
    app.add_handler(CommandHandler("listusers", listusers))

    print("✅ Bot started with UPI + IFSC features")
    app.run_polling()

if __name__ == "__main__":
    main()
