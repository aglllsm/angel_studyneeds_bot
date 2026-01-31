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
import os
import json
import tempfile
import gspread
from google.oauth2.service_account import Credentials

from apps_config import APPS, BULANAN_MIN_DAYS

# ==========================================================
# CONFIG (Railway Variables)
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
    items = list(APPS.items())
    buttons = []
    row = []
    for k, v in items:
        icon = v.get("icon", "✨")
        title = v.get("title", k)
        row.append(
            InlineKeyboardButton(f"{icon} {title}", callback_data=f"{prefix}:{k}")
        )
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


def norm_text(t: str) -> str:
    t = (t or "").strip()
    t = " ".join(t.split())
    return t


def is_menu_check(t: str) -> bool:
    t = norm_text(t)
    return t.endswith("Cek Email") or t == "Cek Email"


def is_menu_add(t: str) -> bool:
    t = norm_text(t)
    return t.endswith("Tambah Akun") or t == "Tambah Akun"


def is_menu_list(t: str) -> bool:
    t = norm_text(t)
    return t.endswith("Cek List") or t == "Cek List"


def is_menu_delete(t: str) -> bool:
    t = norm_text(t)
    return t.endswith("Hapus Email Dobel") or t == "Hapus Email Dobel"


def is_menu_owner(t: str) -> bool:
    t = norm_text(t)
    return t.endswith("Set Owner") or t == "Set Owner"


def is_menu_help(t: str) -> bool:
    t = norm_text(t)
    return t.endswith("Bantuan") or t == "Bantuan"


# ==========================================================
# GOOGLE SHEET (cache biar gak authorize terus)
# ==========================================================
_GC = None
_SH = None


def get_spreadsheet():
    global _GC, _SH
    if _SH is not None:
        return _SH

    if "GSHEET_CREDS_JSON" not in os.environ:
        raise RuntimeError("ENV GSHEET_CREDS_JSON belum di-set di Railway.")

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]

    data = json.loads(os.environ["GSHEET_CREDS_JSON"])
    fd, path = tempfile.mkstemp(suffix=".json")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f)
        creds = Credentials.from_service_account_file(path, scopes=scopes)
        _GC = gspread.authorize(creds)
        _SH = _GC.open(SHEET_NAME)
        return _SH
    finally:
        try:
            os.remove(path)
        except Exception:
            pass


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
    except Exception:
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
    await update.message.reply_text(
        "🤍 Angel Studyneeds Bot", reply_markup=main_menu_kb()
    )


async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "ℹ️ Bantuan\n"
        "- ➕ Tambah Akun: pilih aplikasi → email → durasi (hari) → nomor WA\n"
        "- 🔎 Cek Email: cari email di semua aplikasi\n"
        "- 📋 Cek List: ringkasan akun per aplikasi\n"
        "- 🗑 Hapus Email Dobel: bersihin duplikat email\n"
        "- ⚙️ Set Owner: set chat kamu sebagai penerima reminder\n\n"
        "Ketik /cancel untuk batal saat proses input.\n\n"
        "Command cepat:\n"
        "/add, /cek, /list, /dupes, /owner",
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
    if update.message:
        await update.message.reply_text("❌ Dibatalkan.", reply_markup=main_menu_kb())
    return ConversationHandler.END


async def cancel_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    try:
        await q.edit_message_text("❌ Dibatalkan.")
    except Exception:
        pass
    ctx.user_data.clear()
    return ConversationHandler.END

async def conv_timeout(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    if update.message:
        await update.message.reply_text("⏳ Timeout. Ulangi dari menu ya.", reply_markup=main_menu_kb())
    return ConversationHandler.END


# ==========================================================
# ENTRY POINTS
# ==========================================================
async def entry_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Pilih aplikasi yang mau ditambah:", reply_markup=apps_inline_kb("ADD")
    )
    return ADD_PICK_APP


async def entry_check(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Ketik email yang mau dicek (contoh: user@gmail.com)\n/cancel untuk batal"
    )
    return CHECK_EMAIL


# ==========================================================
# MENU NON-CONV (tombol lain)
# ==========================================================
async def handle_menu_other(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if ctx.user_data:
        return

    text = norm_text(update.message.text)

    if is_menu_list(text):
        await dashboard(update, ctx)
        return
    if is_menu_delete(text):
        await delete_duplicates_all(update, ctx)
        return
    if is_menu_owner(text):
        await set_owner(update, ctx)
        return
    if is_menu_help(text):
        await help_cmd(update, ctx)
        return

    # selain tombol menu -> DIAM
    return

# ==========================================================
# ADD FLOW
# ==========================================================
async def add_pick_app_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.data == "CANCEL":
        return await cancel_cb(update, ctx)

    if ":" not in q.data:
        await q.edit_message_text("❌ Callback tidak valid.")
        return ConversationHandler.END

    prefix, app_key = q.data.split(":", 1)
    if prefix != "ADD":
        return ConversationHandler.END

    if app_key not in APPS:
        await q.edit_message_text("❌ App tidak dikenali.")
        return ConversationHandler.END

    ctx.user_data["add_app"] = app_key
    await q.edit_message_text(
        f"{APPS[app_key].get('icon','✨')} {APPS[app_key]['title']}\n"
        "Masukkan email akun:\n/cancel untuk batal"
    )
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
        "created_datetime",
        "email",
        "duration_days",
        "expire_datetime",
        "status",
        "customer_phone",
        "rem14_sent",
        "rem7_sent",
        "rem3_sent",
        "rem1h_sent",
        "rem1d_sent",
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
# DASHBOARD
# ==========================================================
async def dashboard(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    sh = get_spreadsheet()
    now = datetime.now()
    lines = ["📊 DASHBOARD\n"]

    for _, v in APPS.items():
        ws = sh.worksheet(v["sheet"])
        rows = ws.get_all_records()
        a = e = h3 = h7 = h14 = today = 0
        for r in rows:
            try:
                exp = parse_dt(r["expire_datetime"])
                secs = (exp - now).total_seconds()
                if secs <= 0:
                    e += 1
                    continue
                a += 1
                d = secs / 86400
                if d <= 14:
                    h14 += 1
                if d <= 7:
                    h7 += 1
                if d <= 3:
                    h3 += 1
                if d <= 0.01:
                    today += 1
            except Exception:
                pass

        lines.append(
            f"{v.get('icon','✨')} {v['title']}\n"
            f"Active: {a} | Expired: {e}\n"
            f"H14: {h14} | H7: {h7} | H3: {h3} | Today: {today}\n"
        )

    await update.message.reply_text("\n".join(lines), reply_markup=main_menu_kb())


# ==========================================================
# CHECK EMAIL FLOW
# ==========================================================
async def check_email_step(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    email = (update.message.text or "").strip()
    if not is_valid_email(email):
        await update.message.reply_text("❌ Email tidak valid. Coba lagi:\n/cancel untuk batal")
        return CHECK_EMAIL

    # DEBUG (hapus nanti kalau sudah beres)
    await update.message.reply_text("DEBUG: masuk check_email_step")

    sh = get_spreadsheet()
    now = datetime.now()
    email_l = email.lower()

    lines = [f"🔎 HASIL CEK: {email}\n"]
    found = False
    errors = []

    for app_key, v in APPS.items():
        try:
            ws = sh.worksheet(v["sheet"])      # bisa error kalau nama tab beda
            values = ws.get_all_values()       # lebih cepat dari get_all_records
            if not values or len(values) < 2:
                continue

            headers = [h.strip() for h in values[0]]
            if "email" not in headers:
                continue

            idx_email = headers.index("email")
            idx_exp = headers.index("expire_datetime") if "expire_datetime" in headers else None
            idx_status = headers.index("status") if "status" in headers else None
            idx_phone = headers.index("customer_phone") if "customer_phone" in headers else None

            for row in values[1:]:
                row_email = (row[idx_email] if idx_email < len(row) else "").strip().lower()
                if row_email != email_l:
                    continue

                found = True
                exp_str = row[idx_exp] if (idx_exp is not None and idx_exp < len(row)) else "-"
                status = row[idx_status] if (idx_status is not None and idx_status < len(row)) else "-"
                phone = row[idx_phone] if (idx_phone is not None and idx_phone < len(row)) else ""

                try:
                    exp = parse_dt(exp_str)
                    sisa = human(exp - now)
                except Exception:
                    sisa = "?"

                lines.append(
                    f"{v.get('icon','✨')} {v.get('title', app_key)}\n"
                    f"Expire: {exp_str} ({sisa})\n"
                    f"Status: {status}\n"
                    f"HP: {mask_phone(phone)}\n"
                )

        except Exception as e:
            errors.append(f"{v.get('title', app_key)}: {type(e).__name__}")
            continue

    if not found:
        lines.append("❌ Tidak ketemu di semua app.")

    if errors:
        lines.append("\n⚠️ Ada tab yang error (cek nama tab di Google Sheet):")
        lines.extend([f"- {x}" for x in errors[:10]])

    await update.message.reply_text("\n".join(lines), reply_markup=main_menu_kb())
    return ConversationHandler.END

# ==========================================================
# DELETE DUPLICATES
# ==========================================================
async def delete_duplicates_all(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    sh = get_spreadsheet()
    total_deleted = 0
    per_app = []

    for _, v in APPS.items():
        ws = sh.worksheet(v["sheet"])
        rows = ws.get_all_records()
        seen = set()
        to_delete_rownums = []

        for idx, r in enumerate(rows, start=2):
            em = str(r.get("email", "")).strip().lower()
            if not em:
                continue
            if em in seen:
                to_delete_rownums.append(idx)
            else:
                seen.add(em)

        for rn in sorted(to_delete_rownums, reverse=True):
            ws.delete_rows(rn)

        if to_delete_rownums:
            per_app.append(f"{v['title']}: {len(to_delete_rownums)}")
            total_deleted += len(to_delete_rownums)

    if total_deleted == 0:
        await update.message.reply_text("✅ Tidak ada email dobel.", reply_markup=main_menu_kb())
    else:
        await update.message.reply_text(
            "🗑 Duplikat dihapus:\n" + "\n".join(per_app) + f"\n\nTotal: {total_deleted}",
            reply_markup=main_menu_kb(),
        )


# ==========================================================
# REMINDER JOB
# ==========================================================
async def reminder_job_all_apps(ctx: ContextTypes.DEFAULT_TYPE):
    owner = load_owner()
    if not owner:
        return

    sh = get_spreadsheet()
    now = datetime.now()

    for _, v in APPS.items():
        ws = sh.worksheet(v["sheet"])
        rows = ws.get_all_records()
        msgs = []
        headers = ws.row_values(1)

        def set_flag(i_row: int, colname: str):
            if colname in headers:
                ws.update_cell(i_row, headers.index(colname) + 1, "TRUE")

        def set_status_expired(i_row: int):
            if "status" in headers:
                ws.update_cell(i_row, headers.index("status") + 1, "EXPIRED")

        for i, r in enumerate(rows, start=2):
            try:
                exp = parse_dt(r["expire_datetime"])
                secs = (exp - now).total_seconds()

                if secs <= 0:
                    set_status_expired(i)
                    continue

                days_left = secs / 86400
                dur = int(r.get("duration_days", 0) or 0)

                if dur >= BULANAN_MIN_DAYS:
                    if days_left <= 14 and not _flag(r.get("rem14_sent")):
                        msgs.append(f"{r.get('email','')} | H-14 | {mask_phone(r.get('customer_phone',''))}")
                        set_flag(i, "rem14_sent")
                    if days_left <= 7 and not _flag(r.get("rem7_sent")):
                        msgs.append(f"{r.get('email','')} | H-7 | {mask_phone(r.get('customer_phone',''))}")
                        set_flag(i, "rem7_sent")
                    if days_left <= 3 and not _flag(r.get("rem3_sent")):
                        msgs.append(f"{r.get('email','')} | H-3 | {mask_phone(r.get('customer_phone',''))}")
                        set_flag(i, "rem3_sent")
                    if days_left <= 1 and not _flag(r.get("rem1d_sent")):
                        msgs.append(f"{r.get('email','')} | H-1 | {mask_phone(r.get('customer_phone',''))}")
                        set_flag(i, "rem1d_sent")
                else:
                    if secs / 3600 <= 1 and not _flag(r.get("rem1h_sent")):
                        msgs.append(f"{r.get('email','')} | H-1 JAM | {mask_phone(r.get('customer_phone',''))}")
                        set_flag(i, "rem1h_sent")
            except Exception:
                pass

        if msgs:
            await ctx.bot.send_message(
                owner, f"🔔 {v.get('icon','✨')} {v['title']}\n" + "\n".join(msgs)
            )


# ==========================================================
# MAIN
# ==========================================================
def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN kosong. Set di Railway Variables.")

    app = Application.builder().token(BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("set_owner", set_owner))
    app.add_handler(CommandHandler("owner", set_owner))
    app.add_handler(CommandHandler("cancel", cancel))

    # Command cepat (opsional)
    app.add_handler(CommandHandler("add", entry_add))
    app.add_handler(CommandHandler("cek", entry_check))
    app.add_handler(CommandHandler("list", dashboard))
    app.add_handler(CommandHandler("dupes", delete_duplicates_all))

    # Conversation handler (Tambah Akun & Cek Email)
    conv = ConversationHandler(
    entry_points=[
        MessageHandler(filters.Regex(r".*Tambah Akun$"), entry_add),
        MessageHandler(filters.Regex(r".*Cek Email$"), entry_check),
        CommandHandler("add", entry_add),
        CommandHandler("cek", entry_check),
    ],
    states={
        ADD_PICK_APP: [CallbackQueryHandler(add_pick_app_cb)],
        ADD_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_email)],
        ADD_DAYS: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_days)],
        ADD_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_phone)],
        CHECK_EMAIL: [MessageHandler(filters.ALL & ~filters.COMMAND, check_email_step)],
        ConversationHandler.TIMEOUT: [MessageHandler(filters.ALL, conv_timeout)],
    },
    fallbacks=[
        CommandHandler("cancel", cancel),
        CallbackQueryHandler(cancel_cb, pattern="^CANCEL$"),
    ],
    allow_reentry=True,
    per_chat=True,
    per_user=True,
    per_message=False,
    conversation_timeout=300,
)

    # group 0: conversation harus paling prioritas
    app.add_handler(conv, group=0)

    # group 1: menu umum (jalan hanya untuk tombol menu, dan gak ganggu conversation)
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_menu_other),
        group=1
    )

    # reminder
    app.job_queue.run_repeating(reminder_job_all_apps, interval=3600, first=10)

    app.run_polling()


if __name__ == "__main__":
    main()






