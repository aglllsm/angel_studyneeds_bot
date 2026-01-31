from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application, CommandHandler, ContextTypes,
    ConversationHandler, MessageHandler, CallbackQueryHandler, filters
)
from datetime import datetime, timedelta
import os, json, tempfile
import gspread
from google.oauth2.service_account import Credentials

from apps_config import APPS, BULANAN_MIN_DAYS, REM_DAYS_14, REM_DAYS_7, REM_DAYS_3, REM_HOURS_1

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
        resize_keyboard=True
    )

def apps_inline_kb(prefix: str):
    buttons = []
    row = []
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

def fmt_date(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")

def parse_dt_flexible(s: str) -> datetime:
    s = (s or "").strip()
    if not s:
        raise ValueError("empty date")
    # terima "YYYY-MM-DD HH:MM:SS" atau "YYYY-MM-DD"
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except:
            pass
    raise ValueError(f"unrecognized date format: {s}")

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

def header_alias(headers: list[str], *names: str):
    # cari nama kolom yang cocok dari beberapa kandidat
    lower = [h.strip().lower() for h in headers]
    for n in names:
        n2 = n.strip().lower()
        if n2 in lower:
            return headers[lower.index(n2)]
    return None

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
    if not BOT_TOKEN:
        await update.message.reply_text("❌ BOT_TOKEN belum di-set di Railway.")
        return
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
        reply_markup=main_menu_kb()
    )

async def set_owner(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    save_owner(update.effective_chat.id)
    await update.message.reply_text("✅ Owner disimpan. Reminder akan dikirim ke chat ini.", reply_markup=main_menu_kb())

async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Dibatalkan.", reply_markup=main_menu_kb())
    ctx.user_data.clear()
    return ConversationHandler.END

async def cancel_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text("❌ Dibatalkan.")
    ctx.user_data.clear()
    return ConversationHandler.END

# ==========================================================
# ENTRY POINTS (khusus biar nggak “no respon”)
# ==========================================================
async def entry_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Pilih aplikasi yang mau ditambah:", reply_markup=apps_inline_kb("ADD"))
    return ADD_PICK_APP

async def entry_check(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Ketik email yang mau dicek (contoh: user@gmail.com)\n/cancel untuk batal")
    return CHECK_EMAIL

# ==========================================================
# ADD FLOW
# ==========================================================
async def add_pick_app_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.data == "CANCEL":
        return await cancel_cb(update, ctx)

    prefix, app_key = q.data.split(":", 1)
    if prefix != "ADD":
        return ConversationHandler.END

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

    col_created = header_alias(headers, "created_datetime", "timestamp")
    col_email   = header_alias(headers, "email")
    col_dur     = header_alias(headers, "duration_days")
    col_exp     = header_alias(headers, "expire_datetime", "expire_date")
    col_status  = header_alias(headers, "status")
    col_phone   = header_alias(headers, "customer_phone")
    col_note    = header_alias(headers, "note")

    required = [col_email, col_dur, col_exp, col_status, col_phone]
    if any(x is None for x in required):
        await update.message.reply_text(
            "❌ Header sheet kamu belum cocok.\n"
            "Minimal harus ada kolom: email, duration_days, expire_date/expire_datetime, status, customer_phone.\n"
            "Kalau sudah ada, pastikan namanya persis (case bebas).",
            reply_markup=main_menu_kb()
        )
        ctx.user_data.clear()
        return ConversationHandler.END

    row_map = {}
    if col_created:
        row_map[col_created] = fmt_dt(now)  # timestamp juga boleh datetime
    row_map[col_email]  = email
    row_map[col_dur]    = days

    # kalau sheet kamu pakai expire_date (date only), kita simpan date
    if col_exp.strip().lower() == "expire_date":
        row_map[col_exp] = fmt_date(exp)
    else:
        row_map[col_exp] = fmt_dt(exp)

    row_map[col_status] = "ACTIVE"
    row_map[col_phone]  = phone
    if col_note:
        row_map[col_note] = ""

    # flags kalau ada (opsional)
    for opt in ("rem14_sent","rem7_sent","rem3_sent","rem1h_sent","rem1d_sent"):
        c = header_alias(headers, opt)
        if c:
            row_map[c] = ""

    new_row = [row_map.get(h, "") for h in headers]
    ws.append_row(new_row, value_input_option="USER_ENTERED")

    await update.message.reply_text(
        "✅ Akun tersimpan!\n"
        f"App: {APPS[app_key]['title']}\n"
        f"Email: {email}\n"
        f"Durasi: {days} hari\n"
        f"Expire: {row_map[col_exp]}\n"
        f"HP: {phone}",
        reply_markup=main_menu_kb()
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

    for k, v in APPS.items():
        ws = sh.worksheet(v["sheet"])
        rows = ws.get_all_records()
        a = e = h3 = h7 = h14 = today = 0

        for r in rows:
            try:
                exp_s = str(r.get("expire_datetime") or r.get("expire_date") or "").strip()
                exp = parse_dt_flexible(exp_s)
                secs = (exp - now).total_seconds()
                if secs <= 0:
                    e += 1
                    continue
                a += 1
                d = secs / 86400
                if d <= 14: h14 += 1
                if d <= 7:  h7 += 1
                if d <= 3:  h3 += 1
                if d <= 0.01: today += 1
            except:
                pass

        lines.append(
            f"{v.get('icon','✨')} {v['title']}\n"
            f"Active: {a} | Expired: {e}\n"
            f"H14: {h14} | H7: {h7} | H3: {h3} | Today: {today}\n"
        )

    await update.message.reply_text("\n".join(lines), reply_markup=main_menu_kb())

# ==========================================================
# CHECK EMAIL
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
                exp_s = str(r.get("expire_datetime") or r.get("expire_date") or "-")
                try:
                    td = parse_dt_flexible(exp_s) - now
                    sisa = human(td)
                except:
                    sisa = "?"
                lines.append(
                    f"{v.get('icon','✨')} {v['title']}\n"
                    f"Expire: {exp_s} ({sisa})\n"
                    f"Status: {r.get('status','-')}\n"
                    f"HP: {mask_phone(str(r.get('customer_phone','')))}\n"
                )

    if not found:
        await update.message.reply_text("❌ Tidak ketemu di semua app.", reply_markup=main_menu_kb())
    else:
        await update.message.reply_text("\n".join(lines), reply_markup=main_menu_kb())

    return ConversationHandler.END

# ==========================================================
# DELETE DUPLICATES
# ==========================================================
async def delete_duplicates_all(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    sh = get_spreadsheet()
    total_deleted = 0
    per_app = []

    for k, v in APPS.items():
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
            reply_markup=main_menu_kb()
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

    for k, v in APPS.items():
        ws = sh.worksheet(v["sheet"])
        headers = ws.row_values(1)
        rows = ws.get_all_records()
        msgs = []

        # cari kolom flags (opsional)
        col_status_name = header_alias(headers, "status")
        def col_index(name: str):
            if not name:
                return None
            return headers.index(name) + 1

        for i, r in enumerate(rows, start=2):
            try:
                exp_s = str(r.get("expire_datetime") or r.get("expire_date") or "").strip()
                exp = parse_dt_flexible(exp_s)
                secs = (exp - now).total_seconds()

                if secs <= 0:
                    if col_status_name:
                        ws.update_cell(i, col_index(col_status_name), "EXPIRED")
                    continue

                days_left = secs / 86400
                dur = int(r.get("duration_days", 0) or 0)

                def set_flag(flag_name: str):
                    cname = header_alias(headers, flag_name)
                    if cname:
                        ws.update_cell(i, col_index(cname), "TRUE")

                if dur >= BULANAN_MIN_DAYS:
                    if days_left <= REM_DAYS_14 and not _flag(r.get("rem14_sent")):
                        msgs.append(f"{r.get('email','')} | H-14 | {mask_phone(str(r.get('customer_phone','')))}")
                        set_flag("rem14_sent")
                    if days_left <= REM_DAYS_7 and not _flag(r.get("rem7_sent")):
                        msgs.append(f"{r.get('email','')} | H-7 | {mask_phone(str(r.get('customer_phone','')))}")
                        set_flag("rem7_sent")
                    if days_left <= REM_DAYS_3 and not _flag(r.get("rem3_sent")):
                        msgs.append(f"{r.get('email','')} | H-3 | {mask_phone(str(r.get('customer_phone','')))}")
                        set_flag("rem3_sent")
                    if days_left <= 1 and not _flag(r.get("rem1d_sent")):
                        msgs.append(f"{r.get('email','')} | H-1 | {mask_phone(str(r.get('customer_phone','')))}")
                        set_flag("rem1d_sent")
                else:
                    if secs / 3600 <= REM_HOURS_1 and not _flag(r.get("rem1h_sent")):
                        msgs.append(f"{r.get('email','')} | H-1 JAM | {mask_phone(str(r.get('customer_phone','')))}")
                        set_flag("rem1h_sent")
            except:
                pass

        if msgs:
            await ctx.bot.send_message(owner, f"🔔 {v['title']}\n" + "\n".join(msgs))

# ==========================================================
# MAIN
# ==========================================================
async def unknown_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    # handler umum buat menu di luar conversation
    text = (update.message.text or "").strip()
    if text == MENU_LIST:
        await dashboard(update, ctx)
    elif text == MENU_DELETE:
        await delete_duplicates_all(update, ctx)
    elif text == MENU_OWNER:
        await set_owner(update, ctx)
    elif text == MENU_HELP:
        await help_cmd(update, ctx)
    else:
        await update.message.reply_text("Pilih menu ya 🙂", reply_markup=main_menu_kb())

def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN kosong. Set di Railway Variables.")

    app = Application.builder().token(BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("set_owner", set_owner))
    app.add_handler(CommandHandler("dashboard", dashboard))
    app.add_handler(CommandHandler("cancel", cancel))

    # Conversation khusus: ADD & CHECK
    conv = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex(f"^{MENU_ADD}$"), entry_add),
            MessageHandler(filters.Regex(f"^{MENU_CHECK}$"), entry_check),
        ],
        states={
            ADD_PICK_APP: [CallbackQueryHandler(add_pick_app_cb)],
            ADD_EMAIL:    [MessageHandler(filters.TEXT & ~filters.COMMAND, add_email)],
            ADD_DAYS:     [MessageHandler(filters.TEXT & ~filters.COMMAND, add_days)],
            ADD_PHONE:    [MessageHandler(filters.TEXT & ~filters.COMMAND, add_phone)],
            CHECK_EMAIL:  [MessageHandler(filters.TEXT & ~filters.COMMAND, check_email_step)],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CallbackQueryHandler(cancel_cb, pattern="^CANCEL$"),
        ],
        allow_reentry=False,  # penting: biar state nggak ke-reset
    )
    app.add_handler(conv)

    # Handler menu lain (list/delete/owner/help)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unknown_text))

    # Reminder job
    app.job_queue.run_repeating(reminder_job_all_apps, interval=3600, first=10)

    app.run_polling()

if __name__ == "__main__":
    main()
