from telegram import (
    Update,
    ReplyKeyboardMarkup,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)
from datetime import datetime, timedelta
import os, json, tempfile
import gspread
from google.oauth2.service_account import Credentials

from apps_config import APPS, BULANAN_MIN_DAYS

# ==========================================================
# CONFIG
# ==========================================================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
SHEET_NAME = os.environ.get("SHEET_NAME", "Angel Studyneeds Sales")
OWNER_FILE = os.environ.get("OWNER_FILE", "/tmp/owner_chat_id.txt")

# ==========================================================
# UI TEXT
# ==========================================================
MENU_ADD = "➕ Tambah Akun"
MENU_LIST = "📋 Cek List"
MENU_CHECK = "🔎 Cek Email"
MENU_DELETE = "🗑 Hapus Email Dobel"
MENU_OWNER = "⚙️ Set Owner"
MENU_HELP = "ℹ️ Bantuan"

def main_menu_kb():
    return ReplyKeyboardMarkup(
        [
            [MENU_ADD, MENU_LIST],
            [MENU_CHECK, MENU_DELETE],
            [MENU_OWNER, MENU_HELP],
        ],
        resize_keyboard=True,
    )

def apps_inline_kb(prefix: str):
    buttons = []
    row = []

    # ✅ Tidak ada hardcode turnitin. Semua dari APPS biar gak dobel.
    for k, v in APPS.items():
        icon = v.get("icon", "✨")
        row.append(InlineKeyboardButton(f"{icon} {v['title']}", callback_data=f"{prefix}:{k}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    buttons.append([InlineKeyboardButton("❌ Batal", callback_data="CANCEL")])
    return InlineKeyboardMarkup(buttons)

# ==========================================================
# HELPERS
# ==========================================================
def is_valid_email(e: str) -> bool:
    e = (e or "").strip()
    return ("@" in e) and ("." in e) and (len(e) >= 6)

def clean_phone(p):
    return "".join(c for c in str(p) if c.isdigit())

def is_valid_phone(p) -> bool:
    return len(clean_phone(p)) >= 8

def mask_phone(p: str) -> str:
    p = str(p or "")
    return p[:4] + "****" + p[-4:] if len(p) >= 8 else p

def fmt_dt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")

def parse_dt(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")

def human(td):
    s = int(td.total_seconds())
    if s <= 0:
        return "❌ HABIS"
    d = s // 86400
    h = (s % 86400) // 3600
    m = (s % 3600) // 60
    if d > 0:
        return f"{d} hari {h} jam"
    if h > 0:
        return f"{h} jam {m} menit"
    return f"{m} menit"

def _flag(v):
    return str(v).strip().lower() in ("1", "true", "yes", "sent", "done")

# ==========================================================
# GOOGLE SHEET
# ==========================================================
def get_spreadsheet():
    if "GSHEET_CREDS_JSON" not in os.environ:
        raise RuntimeError("ENV GSHEET_CREDS_JSON belum di-set di Railway.")
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    data = json.loads(os.environ["GSHEET_CREDS_JSON"])
    fd, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w") as f:
        json.dump(data, f)
    gc = gspread.authorize(Credentials.from_service_account_file(path, scopes=scopes))
    return gc.open(SHEET_NAME)

def ws_for_app(sh, app_key: str):
    if app_key not in APPS:
        raise ValueError("App tidak dikenali.")
    return sh.worksheet(APPS[app_key]["sheet"])

# ==========================================================
# OWNER
# ==========================================================
def save_owner(cid: int):
    with open(OWNER_FILE, "w") as f:
        f.write(str(cid))

def load_owner():
    try:
        return int(open(OWNER_FILE).read().strip())
    except:
        return None

# ==========================================================
# CONVERSATION STATES
# ==========================================================
ADD_PICK_APP, ADD_EMAIL, ADD_DAYS, ADD_PHONE = range(4)
CHECK_EMAIL = 10

# ==========================================================
# COMMANDS
# ==========================================================
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤍 Angel Studyneeds Bot", reply_markup=main_menu_kb())

async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "ℹ️ Bantuan\n"
        "- ➕ Tambah Akun: pilih aplikasi → email → durasi (hari) → nomor WA\n"
        "- 🔎 Cek Email: cari email di semua aplikasi\n"
        "- 📋 Cek List: ringkasan akun per aplikasi\n"
        "- 🗑 Hapus Email Dobel: bersihin duplikat email\n"
        "- ⚙️ Set Owner: set chat kamu sebagai penerima reminder\n\n"
        "Ketik /cancel untuk batal saat proses input.",
        reply_markup=main_menu_kb(),
    )

async def set_owner(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    save_owner(update.effective_chat.id)
    await update.message.reply_text(
        "✅ Owner disimpan. Reminder akan dikirim ke chat ini.",
        reply_markup=main_menu_kb(),
    )

async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    await update.message.reply_text("❌ Dibatalkan.", reply_markup=main_menu_kb())
    return ConversationHandler.END

async def cancel_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    ctx.user_data.clear()
    await q.edit_message_text("❌ Dibatalkan.")
    return ConversationHandler.END

# ==========================================================
# MENU HANDLER (ENTRY POINT)
# ==========================================================
async def handle_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()

    if text == MENU_ADD:
        await update.message.reply_text(
            "Pilih aplikasi yang mau ditambah:",
            reply_markup=apps_inline_kb("ADD"),
        )
        return ADD_PICK_APP

    if text == MENU_CHECK:
        await update.message.reply_text(
            "Ketik email yang mau dicek (contoh: user@gmail.com)\n/cancel untuk batal"
        )
        return CHECK_EMAIL

    if text == MENU_HELP:
        await help_cmd(update, ctx)
        return ConversationHandler.END

    await update.message.reply_text("Pilih menu ya 🙂", reply_markup=main_menu_kb())
    return ConversationHandler.END

# ==========================================================
# ADD FLOW
# ==========================================================
async def add_pick_app_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.data == "CANCEL":
        return await cancel_cb(update, ctx)

    _, app_key = q.data.split(":", 1)
    if app_key not in APPS:
        await q.edit_message_text("❌ App tidak dikenali.")
        return ConversationHandler.END

    ctx.user_data["add_app"] = app_key
    await q.edit_message_text(f"{APPS[app_key].get('icon','✨')} {APPS[app_key]['title']}\nMasukkan email akun:\n/cancel untuk batal")
    return ADD_EMAIL

async def add_email(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    email = (update.message.text or "").strip()
    if not is_valid_email(email):
        await update.message.reply_text("❌ Email tidak valid. Coba lagi:\n/cancel untuk batal")
        return ADD_EMAIL

    ctx.user_data["add_email"] = email
    await update.message.reply_text("Masukkan durasi dalam HARI (contoh 30):\n/cancel untuk batal")
    return ADD_DAYS

async def add_days(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    t = (update.message.text or "").strip()
    if not t.isdigit():
        await update.message.reply_text("❌ Durasi harus angka. Contoh: 30\n/cancel untuk batal")
        return ADD_DAYS

    days = int(t)
    if days <= 0 or days > 3650:
        await update.message.reply_text("❌ Durasi tidak masuk akal. Coba lagi.\n/cancel untuk batal")
        return ADD_DAYS

    ctx.user_data["add_days"] = days
    await update.message.reply_text("Masukkan nomor WA customer (contoh: 08xxxx):\n/cancel untuk batal")
    return ADD_PHONE

async def add_phone(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    phone_raw = (update.message.text or "").strip()
    if not is_valid_phone(phone_raw):
        await update.message.reply_text("❌ Nomor tidak valid. Coba lagi.\n/cancel untuk batal")
        return ADD_PHONE

    phone = clean_phone(phone_raw)
    app_key = ctx.user_data["add_app"]
    email = ctx.user_data["add_email"]
    days = ctx.user_data["add_days"]

    now = datetime.now()
    exp = now + timedelta(days=days)

    sh = get_spreadsheet()
    ws = ws_for_app(sh, app_key)

    headers = ws.row_values(1)
    need = [
        "created_datetime", "email", "duration_days", "expire_datetime", "status",
        "customer_phone", "rem14_sent", "rem7_sent", "rem3_sent", "rem1h_sent", "rem1d_sent"
    ]
    missing = [h for h in need if h not in headers]
    if missing:
        await update.message.reply_text(
            "❌ Header sheet belum lengkap.\n"
            f"Kurang kolom: {', '.join(missing)}\n"
            "Samakan header row 1 sesuai kebutuhan bot.",
            reply_markup=main_menu_kb(),
        )
        ctx.user_data.clear()
        return ConversationHandler.END

    row_map = {
        "created_datetime": fmt_dt(now),
        "email": email,
        "duration_days": days,
        "expire_datetime": fmt_dt(exp),
        "status": "ACTIVE",
        "customer_phone": phone,
        "rem14_sent": "",
        "rem7_sent": "",
        "rem3_sent": "",
        "rem1h_sent": "",
        "rem1d_sent": "",
    }
    new_row = [row_map.get(h, "") for h in headers]
    ws.append_row(new_row, value_input_option="USER_ENTERED")

    await update.message.reply_text(
        "✅ Akun tersimpan!\n"
        f"App: {APPS[app_key]['title']}\n"
        f"Email: {email}\n"
        f"Durasi: {days} hari\n"
        f"Expire: {fmt_dt(exp)}\n"
        f"HP: {phone}",
        reply_markup=main_menu_kb(),
    )

    ctx.user_data.clear()
    return ConversationHandler.END

# ==========================================================
# CHECK EMAIL FLOW
# ==========================================================
async def check_email_step(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    email = (update.message.text or "").strip()
    if not is_valid_email(email):
        await update.message.reply_text("❌ Email tidak valid. Coba lagi:\n/cancel untuk batal")
        return CHECK_EMAIL

    sh = get_spreadsheet()
    now = datetime.now()
    lines = [f"🔎 HASIL CEK: {email}\n"]
    found = False

    for k, v in APPS.items():
        ws = sh.worksheet(v["sheet"])
        rows = ws.get_all_records()
        for r in rows:
            if str(r.get("email", "")).strip().lower() == email.lower():
                found = True
                try:
                    exp = parse_dt(r["expire_datetime"])
                    sisa = human(exp - now)
                except:
                    sisa = "?"
                lines.append(
                    f"{v.get('icon','✨')} {v['title']}\n"
                    f"Expire: {r.get('expire_datetime','-')} ({sisa})\n"
                    f"Status: {r.get('status','-')}\n"
                    f"HP: {mask_phone(str(r.get('customer_phone','')))}\n"
                )

    if not found:
        await update.message.reply_text("❌ Tidak ketemu di semua app.", reply_markup=main_menu_kb())
    else:
        await update.message.reply_text("\n".join(lines), reply_markup=main_menu_kb())

    return ConversationHandler.END

# ==========================================================
# MAIN
# ==========================================================
def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN kosong. Set di Railway Variables.")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("set_owner", set_owner))
    app.add_handler(CommandHandler("cancel", cancel))

    conv = ConversationHandler(
        entry_points=[MessageHandler(filters.TEXT & ~filters.COMMAND, handle_menu)],
        states={
            ADD_PICK_APP: [CallbackQueryHandler(add_pick_app_cb, pattern=r"^(ADD:|CANCEL$)")],
            ADD_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_email)],
            ADD_DAYS: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_days)],
            ADD_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_phone)],
            CHECK_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, check_email_step)],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CallbackQueryHandler(cancel_cb, pattern=r"^CANCEL$"),
        ],
        allow_reentry=True,
        per_message=True,  # ✅ ini kunci biar inline callback gak bikin state lepas
    )
    app.add_handler(conv)

    app.run_polling()

if __name__ == "__main__":
    main()
