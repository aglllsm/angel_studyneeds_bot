from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application, CommandHandler, ContextTypes,
    ConversationHandler, MessageHandler, CallbackQueryHandler, filters
)
from datetime import datetime, timedelta
import os
import json
import tempfile
import gspread
from google.oauth2.service_account import Credentials
from functools import partial

# ambil config apps & rules dari apps_config.py
from apps_config import APPS, BULANAN_MIN_DAYS, REM_DAYS_14, REM_DAYS_7, REM_DAYS_3, REM_HOURS_1

# ==========================================================
# NOTE PENTING (BIAR TIDAK ERROR JOBQUEUE)
# requirements.txt minimal:
# python-telegram-bot[job-queue]
# gspread
# google-auth
# python-dateutil
# pytz
# ==========================================================

# =====================
# KONFIGURASI (AMAN UNTUK RAILWAY)
# =====================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
SHEET_NAME = os.environ.get("SHEET_NAME", "Angel Studyneeds Sales")

# tab untuk log sales/test (opsional)
SALES_SHEET = "sales"

# tab khusus turnitin (tetap)
TURNITIN_SHEET = "turnitin"

# Railway filesystem tidak permanen, simpan owner di /tmp
OWNER_FILE = os.environ.get("OWNER_FILE", "/tmp/owner_chat_id.txt")

# =====================
# MENU UI (ESTETIK)
# =====================
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

def apps_inline_kb(prefix: str) -> InlineKeyboardMarkup:
    """
    prefix:
      ADD   -> pilih aplikasi untuk tambah (step-by-step)
      LIST  -> pilih aplikasi untuk cek list
      CHECK -> pilih aplikasi untuk cek email (nanti bot minta email)
      DEL   -> pilih aplikasi untuk delete by email (anti dobel)
    """
    buttons = []

    # Turnitin selalu di atas
    buttons.append([InlineKeyboardButton("📚 Turnitin", callback_data=f"{prefix}:turnitin")])

    # Apps dari APPS (2 kolom biar rapi)
    row = []
    for k, v in APPS.items():
        title = v.get("title", k)
        row.append(InlineKeyboardButton(f"✨ {title}", callback_data=f"{prefix}:{k}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    buttons.append([InlineKeyboardButton("❌ Batal", callback_data="CANCEL")])
    return InlineKeyboardMarkup(buttons)

# =====================
# HELPERS
# =====================
def is_valid_email(email: str) -> bool:
    e = (email or "").strip()
    return ("@" in e) and ("." in e) and (len(e) >= 6)

def clean_phone(phone: str) -> str:
    return "".join([c for c in str(phone or "") if c.isdigit()])

def is_valid_phone(phone: str) -> bool:
    return len(clean_phone(phone)) >= 8

def fmt_status(status: str) -> str:
    s = (status or "").strip().upper()
    return s if s else "UNKNOWN"

def mask_phone(phone: str) -> str:
    p = str(phone or "").strip()
    if len(p) <= 6:
        return p
    return p[:4] + "****" + p[-4:]

def parse_expire_datetime(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")

def fmt_dt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")

def remaining(expire_dt: datetime) -> timedelta:
    return expire_dt - datetime.now()

def human_remaining(td: timedelta) -> str:
    total_seconds = int(td.total_seconds())
    if total_seconds <= 0:
        return "❌ HABIS"
    days = total_seconds // 86400
    hours = (total_seconds % 86400) // 3600
    minutes = (total_seconds % 3600) // 60
    if days > 0:
        return f"⏳ {days} hari {hours} jam"
    if hours > 0:
        return f"⏳ {hours} jam {minutes} menit"
    return f"⏳ {minutes} menit"

def _flag_is_sent(v) -> bool:
    s = str(v or "").strip().lower()
    return s in ("true", "yes", "1", "sent", "done")

def _app_title(app_key: str) -> str:
    return APPS[app_key]["title"]

def _app_sheet(app_key: str) -> str:
    return APPS[app_key]["sheet"]

# =====================
# GOOGLE SHEET
# =====================
def get_spreadsheet():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]

    creds_json = os.environ.get("GSHEET_CREDS_JSON", "").strip()
    if not creds_json:
        raise RuntimeError(
            "GSHEET_CREDS_JSON belum di-set di Railway Variables. "
            "Isi dengan JSON service account (copy-paste)."
        )

    data = json.loads(creds_json)

    fd, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f)

    creds = Credentials.from_service_account_file(path, scopes=scopes)
    client = gspread.authorize(creds)
    return client.open(SHEET_NAME)

# =====================
# OWNER CHAT ID (UNTUK REMINDER)
# =====================
def save_owner_chat_id(chat_id: int) -> None:
    with open(OWNER_FILE, "w", encoding="utf-8") as f:
        f.write(str(chat_id))

def load_owner_chat_id() -> int | None:
    if not os.path.exists(OWNER_FILE):
        return None
    try:
        with open(OWNER_FILE, "r", encoding="utf-8") as f:
            return int(f.read().strip())
    except Exception:
        return None

# =====================
# BASIC COMMANDS
# =====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "Halo 👋\n"
        "Aku <b>angel-studyneeds-bot</b> 🤍\n\n"
        "Pakai tombol menu di bawah ya 👇\n\n"
        "<b>Quick Commands</b> (opsional):\n"
        "• /set_owner\n"
        "• /test_sheet\n"
        "• /cancel\n"
    )
    await update.message.reply_text(msg, parse_mode="HTML", reply_markup=main_menu_kb())

async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Pilih menu di bawah 👇", reply_markup=main_menu_kb())

async def help_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (
        "ℹ️ <b>Bantuan</b>\n\n"
        f"• <b>{MENU_ADD}</b> → input step-by-step (email → durasi → no HP)\n"
        f"• <b>{MENU_LIST}</b> → lihat 15 data terakhir per aplikasi\n"
        f"• <b>{MENU_CHECK}</b> → cek detail satu email\n"
        f"• <b>{MENU_DELETE}</b> → hapus data dobel berdasarkan email\n"
        f"• <b>{MENU_OWNER}</b> → set chat kamu untuk reminder otomatis\n\n"
        "Tips: kalau habis pilih <b>Cek Email</b>/<b>Hapus</b>, tinggal kirim email-nya.\n"
        "Bisa /cancel untuk batal."
    )
    await update.message.reply_text(txt, parse_mode="HTML", reply_markup=main_menu_kb())

async def set_owner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    save_owner_chat_id(chat_id)
    await update.message.reply_text("✅ Owner tersimpan. Reminder otomatis akan dikirim ke chat ini.", reply_markup=main_menu_kb())

async def test_sheet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        sh = get_spreadsheet()
        ws = sh.worksheet(SALES_SHEET)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ws.append_row([now, "test", "TEST", "TEST", 1, 0, 0, "-", "OK", "tes koneksi"])
        await update.message.reply_text("✅ Berhasil nulis ke Google Sheet!", reply_markup=main_menu_kb())
    except Exception as e:
        await update.message.reply_text(f"❌ Gagal konek ke Sheet:\n{e}", reply_markup=main_menu_kb())

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("✅ Dibatalkan.", reply_markup=main_menu_kb())
    return ConversationHandler.END

# =====================
# ROUTER: REPLY MENU TEXT
# =====================
async def menu_text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (update.message.text or "").strip()

    if txt == MENU_ADD:
        await update.message.reply_text(
            "Pilih aplikasi untuk <b>Tambah Akun</b>:",
            parse_mode="HTML",
            reply_markup=apps_inline_kb("ADD"),
        )
        return

    if txt == MENU_LIST:
        await update.message.reply_text(
            "Pilih aplikasi untuk <b>Cek List</b>:",
            parse_mode="HTML",
            reply_markup=apps_inline_kb("LIST"),
        )
        return

    if txt == MENU_CHECK:
        await update.message.reply_text(
            "Pilih aplikasi untuk <b>Cek Email</b>:",
            parse_mode="HTML",
            reply_markup=apps_inline_kb("CHECK"),
        )
        return

    if txt == MENU_DELETE:
        await update.message.reply_text(
            "Pilih aplikasi untuk <b>Hapus Email Dobel</b>:",
            parse_mode="HTML",
            reply_markup=apps_inline_kb("DEL"),
        )
        return

    if txt == MENU_OWNER:
        await set_owner(update, context)
        return

    if txt == MENU_HELP:
        await help_menu(update, context)
        return

# =====================
# CALLBACK ROUTER (INLINE BUTTONS)
# =====================
async def menu_callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    data = (q.data or "").strip()

    if data == "CANCEL":
        await q.message.reply_text("✅ Oke, dibatalkan.", reply_markup=main_menu_kb())
        return

    if ":" not in data:
        return

    prefix, key = data.split(":", 1)

    # --- ADD (mulai wizard) ---
    if prefix == "ADD":
        if key == "turnitin":
            # set flag biar start bisa dipanggil dari callback
            await add_tii_wizard_start_from_callback(q, context)
            return
        if key in APPS:
            context.user_data["app_key"] = key
            await add_app_wizard_start_from_callback(q, context)
            return

    # --- LIST ---
    if prefix == "LIST":
        if key == "turnitin":
            await cek_tii_from_message(q.message, context)
            return
        if key in APPS:
            await cek_app_list_from_message(q.message, context, key)
            return

    # --- CHECK EMAIL (minta email) ---
    if prefix == "CHECK":
        context.user_data["pending_action"] = "CHECK"
        context.user_data["pending_key"] = key
        title = "Turnitin" if key == "turnitin" else (_app_title(key) if key in APPS else key)
        await q.message.reply_text(
            f"🔎 <b>Cek Email - {title}</b>\n\nKirim email yang mau dicek.\nContoh: <code>example@gmail.com</code>\n\n/cancel untuk batal.",
            parse_mode="HTML",
            reply_markup=main_menu_kb(),
        )
        return

    # --- DELETE (minta email) ---
    if prefix == "DEL":
        context.user_data["pending_action"] = "DEL"
        context.user_data["pending_key"] = key
        title = "Turnitin" if key == "turnitin" else (_app_title(key) if key in APPS else key)
        await q.message.reply_text(
            f"🗑 <b>Hapus Email Dobel - {title}</b>\n\nKirim email yang mau dihapus.\nContoh: <code>example@gmail.com</code>\n\n/cancel untuk batal.",
            parse_mode="HTML",
            reply_markup=main_menu_kb(),
        )
        return

# =====================
# PENDING INPUT (SETELAH PILIH CHECK/DEL)
# =====================
async def pending_email_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # hanya jalan kalau ada pending_action
    action = context.user_data.get("pending_action")
    key = context.user_data.get("pending_key")
    if not action or not key:
        return

    email = (update.message.text or "").strip()
    if not is_valid_email(email):
        await update.message.reply_text("❌ Email tidak valid. Coba lagi atau /cancel.", reply_markup=main_menu_kb())
        return

    try:
        if action == "CHECK":
            if key == "turnitin":
                # reuse existing function by faking command text
                update.message.text = f"/cek_email {email}"
                await cek_email(update, context)
            else:
                update.message.text = f"/cek_{key}_email {email}"
                await cek_app_email(update, context, key)

        elif action == "DEL":
            if key == "turnitin":
                update.message.text = f"/del_tii {email}"
                await del_tii(update, context)
            else:
                update.message.text = f"/del_{key} {email}"
                await del_app_email(update, context, key)

    finally:
        context.user_data.pop("pending_action", None)
        context.user_data.pop("pending_key", None)

# =====================
# TURNITIN (WIZARD + CEK + DELETE)
# =====================
TII_EMAIL, TII_DURASI, TII_PHONE = range(3)

def days_left(expire_str: str) -> int:
    expire_dt = datetime.strptime(expire_str, "%Y-%m-%d")
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    return (expire_dt - today).days

async def add_tii_wizard_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📝 <b>Tambah Turnitin</b>\n\n"
        "1) Kirim <b>EMAIL</b> dulu.\n"
        "Contoh: <code>example@gmail.com</code>\n\n"
        "Ketik /cancel untuk batal.",
        parse_mode="HTML",
        reply_markup=main_menu_kb()
    )
    return TII_EMAIL

async def add_tii_wizard_start_from_callback(q, context: ContextTypes.DEFAULT_TYPE):
    await q.message.reply_text(
        "📝 <b>Tambah Turnitin</b>\n\n"
        "1) Kirim <b>EMAIL</b> dulu.\n"
        "Contoh: <code>example@gmail.com</code>\n\n"
        "Ketik /cancel untuk batal.",
        parse_mode="HTML",
        reply_markup=main_menu_kb()
    )
    # Trick: ConversationHandler will still control state only if started via its entry point.
    # So we store a flag and let the "ADD:turnitin" CallbackQueryHandler entry point start the conv.
    return TII_EMAIL

async def add_tii_wizard_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    email = (update.message.text or "").strip()
    if not is_valid_email(email):
        await update.message.reply_text("❌ Email tidak valid. Coba kirim email yang benar.", reply_markup=main_menu_kb())
        return TII_EMAIL

    context.user_data["tii_email"] = email
    await update.message.reply_text(
        "2) Kirim <b>DURASI (hari)</b>.\nContoh: <code>30</code>\n\n/cancel untuk batal.",
        parse_mode="HTML",
        reply_markup=main_menu_kb()
    )
    return TII_DURASI

async def add_tii_wizard_durasi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (update.message.text or "").strip()
    if not txt.isdigit() or int(txt) <= 0:
        await update.message.reply_text("❌ Durasi harus angka > 0. Contoh: 30", reply_markup=main_menu_kb())
        return TII_DURASI

    context.user_data["tii_duration"] = int(txt)
    await update.message.reply_text(
        "3) Kirim <b>NO HP</b> customer.\nContoh: <code>081234567890</code>\n\n/cancel untuk batal.",
        parse_mode="HTML",
        reply_markup=main_menu_kb()
    )
    return TII_PHONE

async def add_tii_wizard_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone_raw = (update.message.text or "").strip()
    if not is_valid_phone(phone_raw):
        await update.message.reply_text("❌ No HP tidak valid / terlalu pendek. Coba lagi.", reply_markup=main_menu_kb())
        return TII_PHONE

    phone = clean_phone(phone_raw)
    email = context.user_data.get("tii_email")
    duration = int(context.user_data.get("tii_duration", 0))

    try:
        now_dt = datetime.now()
        now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")
        expire_dt = now_dt + timedelta(days=duration)
        expire_str = expire_dt.strftime("%Y-%m-%d")

        sh = get_spreadsheet()
        ws = sh.worksheet(TURNITIN_SHEET)
        ws.append_row([now_str, email, duration, expire_str, "ACTIVE", phone, ""])

        await update.message.reply_text(
            "✅ <b>Turnitin tersimpan</b>\n"
            f"• Email: <code>{email}</code>\n"
            f"• Durasi: <b>{duration}</b> hari\n"
            f"• Expire: <b>{expire_str}</b>\n"
            f"• HP: <code>{phone}</code>",
            parse_mode="HTML",
            reply_markup=main_menu_kb()
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Gagal simpan:\n{e}", reply_markup=main_menu_kb())

    context.user_data.clear()
    return ConversationHandler.END

async def cek_tii(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cek_tii_from_message(update.message, context)

async def cek_tii_from_message(msg, context: ContextTypes.DEFAULT_TYPE):
    try:
        sh = get_spreadsheet()
        ws = sh.worksheet(TURNITIN_SHEET)
        rows = ws.get_all_records()

        if not rows:
            await msg.reply_text("Belum ada data Turnitin.", reply_markup=main_menu_kb())
            return

        rows = rows[-15:]
        lines = ["📄 Daftar Turnitin (15 terakhir):\n"]

        for i, r in enumerate(reversed(rows), start=1):
            email = str(r.get("email", "")).strip()
            expire = str(r.get("expire_date", "")).strip()
            phone = str(r.get("customer_phone", "")).strip()
            status = fmt_status(r.get("status", ""))

            if expire:
                sisa = days_left(expire)
                if sisa < 0:
                    info = f"❌ HABIS ({abs(sisa)} hari lalu)"
                    status = "EXPIRED"
                elif sisa == 0:
                    info = "⚠️ HABIS HARI INI"
                else:
                    info = f"⏳ Sisa {sisa} hari"
            else:
                info = "⚠️ expire tidak ada"

            lines.append(
                f"{i}) {email}\n"
                f"   {info} | Exp: {expire}\n"
                f"   HP: {mask_phone(phone)} | Status: {status}"
            )

        await msg.reply_text("\n\n".join(lines), reply_markup=main_menu_kb())
    except Exception as e:
        await msg.reply_text(f"❌ Error:\n{e}", reply_markup=main_menu_kb())

async def cek_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        email_query = update.message.text.replace("/cek_email", "").strip()
        if not email_query:
            await update.message.reply_text("❌ Format: /cek_email email@domain.com", reply_markup=main_menu_kb())
            return

        sh = get_spreadsheet()
        ws = sh.worksheet(TURNITIN_SHEET)
        rows = ws.get_all_records()

        found = None
        for r in rows:
            if str(r.get("email", "")).strip().lower() == email_query.lower():
                found = r

        if not found:
            await update.message.reply_text("❌ Email tidak ditemukan di data Turnitin.", reply_markup=main_menu_kb())
            return

        email = str(found.get("email", "")).strip()
        expire = str(found.get("expire_date", "")).strip()
        phone = str(found.get("customer_phone", "")).strip()
        status = fmt_status(found.get("status", ""))
        start = str(found.get("timestamp", "")).strip()
        duration = str(found.get("duration_days", "")).strip()

        if expire:
            sisa = days_left(expire)
            if sisa < 0:
                remain_txt = f"❌ <b>Habis</b> ({abs(sisa)} hari lalu)"
                status = "EXPIRED"
            elif sisa == 0:
                remain_txt = "⚠️ <b>Habis hari ini</b>"
            else:
                remain_txt = f"⏳ <b>Sisa {sisa} hari</b>"
        else:
            remain_txt = "⚠️ expire tidak ada"

        msg = (
            "📌 <b>Detail Turnitin</b>\n"
            f"Email: <code>{email}</code>\n"
            f"Mulai: <code>{start}</code>\n"
            f"Durasi: <b>{duration}</b> hari\n"
            f"Expire: <b>{expire}</b>\n"
            f"{remain_txt}\n"
            f"HP: <code>{mask_phone(phone)}</code>\n"
            f"Status: <b>{status}</b>"
        )
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=main_menu_kb())

    except Exception as e:
        await update.message.reply_text(f"❌ Error:\n{e}", reply_markup=main_menu_kb())

async def del_tii(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        email = update.message.text.replace("/del_tii", "").strip()
        if not email:
            await update.message.reply_text("❌ Format:\n/del_tii email@domain.com", reply_markup=main_menu_kb())
            return

        sh = get_spreadsheet()
        ws = sh.worksheet(TURNITIN_SHEET)
        rows = ws.get_all_records()

        target_rows = []
        for i, r in enumerate(rows, start=2):
            if str(r.get("email", "")).strip().lower() == email.lower():
                target_rows.append(i)

        if not target_rows:
            await update.message.reply_text("❌ Email tidak ditemukan di data Turnitin.", reply_markup=main_menu_kb())
            return

        for row_idx in reversed(target_rows):
            ws.delete_rows(row_idx)

        await update.message.reply_text(
            f"🗑️ <b>Turnitin dihapus</b>\n"
            f"Email: <code>{email}</code>\n"
            f"Jumlah data dihapus: <b>{len(target_rows)}</b>",
            parse_mode="HTML",
            reply_markup=main_menu_kb()
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Error:\n{e}", reply_markup=main_menu_kb())

# =====================
# GENERIC ENGINE: CANVA-LIKE APPS (from APPS)
# =====================
APP_EMAIL, APP_DURASI, APP_PHONE = range(20, 23)

async def add_app_wizard_start_from_callback(q, context: ContextTypes.DEFAULT_TYPE):
    app_key = context.user_data.get("app_key")
    if not app_key or app_key not in APPS:
        await q.message.reply_text("⚠️ App tidak valid. Klik menu lagi ya.", reply_markup=main_menu_kb())
        return APP_EMAIL
    await q.message.reply_text(
        f"📝 <b>Tambah {_app_title(app_key)}</b>\n\n"
        "1) Kirim <b>EMAIL</b> dulu.\n"
        "Contoh: <code>example@gmail.com</code>\n\n"
        "Ketik /cancel untuk batal.",
        parse_mode="HTML",
        reply_markup=main_menu_kb()
    )
    return APP_EMAIL

def build_app_conversation(app_key: str) -> ConversationHandler:
    async def _start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
        context.user_data["app_key"] = app_key
        await update.message.reply_text(
            f"📝 <b>Tambah {_app_title(app_key)}</b>\n\n"
            "1) Kirim <b>EMAIL</b> dulu.\n"
            "Contoh: <code>example@gmail.com</code>\n\n"
            "Ketik /cancel untuk batal.",
            parse_mode="HTML",
            reply_markup=main_menu_kb()
        )
        return APP_EMAIL

    async def _start_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
        q = update.callback_query
        await q.answer()
        context.user_data["app_key"] = app_key
        await q.message.reply_text(
            f"📝 <b>Tambah {_app_title(app_key)}</b>\n\n"
            "1) Kirim <b>EMAIL</b> dulu.\n"
            "Contoh: <code>example@gmail.com</code>\n\n"
            "Ketik /cancel untuk batal.",
            parse_mode="HTML",
            reply_markup=main_menu_kb()
        )
        return APP_EMAIL

    async def _email(update: Update, context: ContextTypes.DEFAULT_TYPE):
        email = (update.message.text or "").strip()
        if not is_valid_email(email):
            await update.message.reply_text("❌ Email tidak valid. Coba lagi.", reply_markup=main_menu_kb())
            return APP_EMAIL
        context.user_data["app_email"] = email
        await update.message.reply_text(
            "2) Kirim <b>DURASI (hari)</b>.\nContoh: <code>30</code>\n\n/cancel untuk batal.",
            parse_mode="HTML",
            reply_markup=main_menu_kb()
        )
        return APP_DURASI

    async def _durasi(update: Update, context: ContextTypes.DEFAULT_TYPE):
        txt = (update.message.text or "").strip()
        if not txt.isdigit() or int(txt) <= 0:
            await update.message.reply_text("❌ Durasi harus angka > 0. Contoh: 30", reply_markup=main_menu_kb())
            return APP_DURASI
        context.user_data["app_duration"] = int(txt)
        await update.message.reply_text(
            "3) Kirim <b>NO HP</b> customer.\nContoh: <code>081234567890</code>\n\n/cancel untuk batal.",
            parse_mode="HTML",
            reply_markup=main_menu_kb()
        )
        return APP_PHONE

    async def _phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
        phone_raw = (update.message.text or "").strip()
        if not is_valid_phone(phone_raw):
            await update.message.reply_text("❌ No HP tidak valid / terlalu pendek. Coba lagi.", reply_markup=main_menu_kb())
            return APP_PHONE

        email = context.user_data.get("app_email")
        duration = int(context.user_data.get("app_duration", 0))
        phone = clean_phone(phone_raw)

        try:
            now_dt = datetime.now()
            expire_dt = now_dt + timedelta(days=duration)

            sh = get_spreadsheet()
            ws = sh.worksheet(_app_sheet(app_key))
            ws.append_row([
                fmt_dt(now_dt),          # timestamp
                email,                   # email
                duration,                # duration_days
                fmt_dt(expire_dt),       # expire_datetime
                "ACTIVE",                # status
                phone,                   # customer_phone
                "",                      # note
                "", "", "", ""           # flags reminder
            ])

            await update.message.reply_text(
                f"✅ <b>{_app_title(app_key)} tersimpan</b>\n"
                f"• Email: <code>{email}</code>\n"
                f"• Durasi: <b>{duration}</b> hari\n"
                f"• Expire: <b>{fmt_dt(expire_dt)}</b>\n"
                f"• HP: <code>{phone}</code>",
                parse_mode="HTML",
                reply_markup=main_menu_kb()
            )
        except Exception as e:
            await update.message.reply_text(f"❌ Gagal simpan:\n{e}", reply_markup=main_menu_kb())

        context.user_data.clear()
        return ConversationHandler.END

    return ConversationHandler(
        entry_points=[
            CommandHandler(f"add_{app_key}", _start_cmd),
            CallbackQueryHandler(_start_cb, pattern=f"^ADD:{app_key}$"),
        ],
        states={
            APP_EMAIL:  [MessageHandler(filters.TEXT & ~filters.COMMAND, _email)],
            APP_DURASI: [MessageHandler(filters.TEXT & ~filters.COMMAND, _durasi)],
            APP_PHONE:  [MessageHandler(filters.TEXT & ~filters.COMMAND, _phone)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

async def cek_app_list(update: Update, context: ContextTypes.DEFAULT_TYPE, app_key: str):
    await cek_app_list_from_message(update.message, context, app_key)

async def cek_app_list_from_message(msg, context: ContextTypes.DEFAULT_TYPE, app_key: str):
    try:
        sh = get_spreadsheet()
        ws = sh.worksheet(_app_sheet(app_key))
        rows = ws.get_all_records()
        if not rows:
            await msg.reply_text(f"Belum ada data {_app_title(app_key)}.", reply_markup=main_menu_kb())
            return

        rows = rows[-15:]
        lines = [f"📄 Daftar {_app_title(app_key)} (15 terakhir):\n"]

        for i, r in enumerate(reversed(rows), start=1):
            email = str(r.get("email", "")).strip()
            exp_str = str(r.get("expire_datetime", "")).strip()
            phone = str(r.get("customer_phone", "")).strip()
            status = fmt_status(r.get("status", ""))

            if exp_str:
                exp_dt = parse_expire_datetime(exp_str)
                td = remaining(exp_dt)
                info = human_remaining(td)
                if td.total_seconds() <= 0:
                    status = "EXPIRED"
            else:
                info = "⚠️ expire tidak ada"

            lines.append(
                f"{i}) {email}\n"
                f"   {info} | Exp: {exp_str}\n"
                f"   HP: {mask_phone(phone)} | Status: {status}"
            )

        await msg.reply_text("\n\n".join(lines), reply_markup=main_menu_kb())
    except Exception as e:
        await msg.reply_text(f"❌ Error:\n{e}", reply_markup=main_menu_kb())

async def cek_app_email(update: Update, context: ContextTypes.DEFAULT_TYPE, app_key: str):
    try:
        cmd = f"/cek_{app_key}_email"
        email_query = update.message.text.replace(cmd, "").strip()
        if not email_query:
            await update.message.reply_text(f"❌ Format: {cmd} email@domain.com", reply_markup=main_menu_kb())
            return

        sh = get_spreadsheet()
        ws = sh.worksheet(_app_sheet(app_key))
        rows = ws.get_all_records()

        found = None
        for r in rows:
            if str(r.get("email", "")).strip().lower() == email_query.lower():
                found = r

        if not found:
            await update.message.reply_text(f"❌ Email tidak ditemukan di data {_app_title(app_key)}.", reply_markup=main_menu_kb())
            return

        email = str(found.get("email", "")).strip()
        exp_str = str(found.get("expire_datetime", "")).strip()
        phone = str(found.get("customer_phone", "")).strip()
        status = fmt_status(found.get("status", ""))
        start = str(found.get("timestamp", "")).strip()
        duration = str(found.get("duration_days", "")).strip()

        if exp_str:
            exp_dt = parse_expire_datetime(exp_str)
            td = remaining(exp_dt)
            remain_txt = human_remaining(td)
            if td.total_seconds() <= 0:
                status = "EXPIRED"
                remain_txt = "❌ HABIS"
        else:
            remain_txt = "⚠️ expire tidak ada"

        msg = (
            f"✨ <b>Detail {_app_title(app_key)}</b>\n"
            f"Email: <code>{email}</code>\n"
            f"Mulai: <code>{start}</code>\n"
            f"Durasi: <b>{duration}</b> hari\n"
            f"Expire: <b>{exp_str}</b>\n"
            f"Sisa: <b>{remain_txt}</b>\n"
            f"HP: <code>{mask_phone(phone)}</code>\n"
            f"Status: <b>{status}</b>"
        )
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=main_menu_kb())
    except Exception as e:
        await update.message.reply_text(f"❌ Error:\n{e}", reply_markup=main_menu_kb())

async def del_app_email(update: Update, context: ContextTypes.DEFAULT_TYPE, app_key: str):
    try:
        cmd = f"/del_{app_key}"
        email = update.message.text.replace(cmd, "").strip()
        if not email:
            await update.message.reply_text(f"❌ Format:\n{cmd} email@domain.com", reply_markup=main_menu_kb())
            return

        sh = get_spreadsheet()
        ws = sh.worksheet(_app_sheet(app_key))
        rows = ws.get_all_records()

        target_rows = []
        for i, r in enumerate(rows, start=2):
            if str(r.get("email", "")).strip().lower() == email.lower():
                target_rows.append(i)

        if not target_rows:
            await update.message.reply_text(f"❌ Email tidak ditemukan di data {_app_title(app_key)}.", reply_markup=main_menu_kb())
            return

        for row_idx in reversed(target_rows):
            ws.delete_rows(row_idx)

        await update.message.reply_text(
            f"🗑️ <b>{_app_title(app_key)} dihapus</b>\n"
            f"Email: <code>{email}</code>\n"
            f"Jumlah data dihapus: <b>{len(target_rows)}</b>",
            parse_mode="HTML",
            reply_markup=main_menu_kb()
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Error:\n{e}", reply_markup=main_menu_kb())

# =====================
# REMINDER JOB (OTOMATIS) - SEMUA APP DI APPS
# =====================
async def reminder_job_all_apps(context: ContextTypes.DEFAULT_TYPE):
    owner_chat_id = load_owner_chat_id()
    if not owner_chat_id:
        return

    for app_key in APPS.keys():
        try:
            sh = get_spreadsheet()
            ws = sh.worksheet(_app_sheet(app_key))
            rows = ws.get_all_records()
            if not rows:
                continue

            remind_msgs = []

            for idx, r in enumerate(rows, start=2):
                email = str(r.get("email", "")).strip()
                exp_str = str(r.get("expire_datetime", "")).strip()
                phone = str(r.get("customer_phone", "")).strip()
                try:
                    duration_days = int(r.get("duration_days", 0) or 0)
                except Exception:
                    duration_days = 0

                if not email or not exp_str:
                    continue

                exp_dt = parse_expire_datetime(exp_str)
                td = remaining(exp_dt)
                secs = td.total_seconds()

                # update status kalau habis
                if secs <= 0:
                    if str(r.get("status", "")).strip().upper() != "EXPIRED":
                        ws.update_cell(idx, 5, "EXPIRED")
                    continue

                title = _app_title(app_key)

                # bulanan: 14/7/3 hari
                if duration_days >= BULANAN_MIN_DAYS:
                    days_left_float = secs / 86400.0

                    rem14_sent = _flag_is_sent(r.get("rem14_sent", ""))
                    rem7_sent = _flag_is_sent(r.get("rem7_sent", ""))
                    rem3_sent = _flag_is_sent(r.get("rem3_sent", ""))

                    if (days_left_float <= REM_DAYS_14) and (not rem14_sent):
                        remind_msgs.append(f"🔔 {title} 14 hari lagi\n{email}\nExp: {exp_str}\nHP: {mask_phone(phone)}")
                        ws.update_cell(idx, 8, "TRUE")

                    if (days_left_float <= REM_DAYS_7) and (not rem7_sent):
                        remind_msgs.append(f"🔔 {title} 7 hari lagi\n{email}\nExp: {exp_str}\nHP: {mask_phone(phone)}")
                        ws.update_cell(idx, 9, "TRUE")

                    if (days_left_float <= REM_DAYS_3) and (not rem3_sent):
                        remind_msgs.append(f"⚠️ {title} H-3 (siap-siap kick)\n{email}\nExp: {exp_str}\nHP: {mask_phone(phone)}")
                        ws.update_cell(idx, 10, "TRUE")

                # < 7 hari: H-1 jam
                elif duration_days < 7:
                    rem1h_sent = _flag_is_sent(r.get("rem1h_sent", ""))
                    hours_left = secs / 3600.0

                    if (hours_left <= REM_HOURS_1) and (hours_left > 0) and (not rem1h_sent):
                        remind_msgs.append(
                            f"⏰ {title} H-1 JAM\n"
                            f"{email}\nExp: {exp_str}\nSisa: {human_remaining(td)}\nHP: {mask_phone(phone)}"
                        )
                        ws.update_cell(idx, 11, "TRUE")

            for msg in remind_msgs[:20]:
                await context.bot.send_message(chat_id=owner_chat_id, text=msg)

        except Exception:
            pass

# =====================
# MAIN
# =====================
def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN belum di-set di Railway Variables!")

    app = Application.builder().token(BOT_TOKEN).build()

    # basic
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(CommandHandler("set_owner", set_owner))
    app.add_handler(CommandHandler("test_sheet", test_sheet))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CommandHandler("help", help_menu))

    # menu text buttons router
    app.add_handler(MessageHandler(filters.Regex(f"^({MENU_ADD}|{MENU_LIST}|{MENU_CHECK}|{MENU_DELETE}|{MENU_OWNER}|{MENU_HELP})$"), menu_text_router))

    # callback router (inline keyboard)
    app.add_handler(CallbackQueryHandler(menu_callback_router))

    # turnitin delete + cek
    app.add_handler(CommandHandler("del_tii", del_tii))
    app.add_handler(CommandHandler("cek_tii", cek_tii))
    app.add_handler(CommandHandler("cek_email", cek_email))

    # wizard turnitin (command entry point)
    tii_conv = ConversationHandler(
        entry_points=[CommandHandler("add_tii", add_tii_wizard_start)],
        states={
            TII_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_tii_wizard_email)],
            TII_DURASI: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_tii_wizard_durasi)],
            TII_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_tii_wizard_phone)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    app.add_handler(tii_conv)

    # register all canva-like apps from APPS (wizard + commands)
    for app_key in APPS.keys():
        # wizard add (command + callback entrypoint)
        app.add_handler(build_app_conversation(app_key))

        # cek list
        app.add_handler(CommandHandler(f"cek_{app_key}", partial(cek_app_list, app_key=app_key)))

        # cek email
        app.add_handler(CommandHandler(f"cek_{app_key}_email", partial(cek_app_email, app_key=app_key)))

        # delete double
        app.add_handler(CommandHandler(f"del_{app_key}", partial(del_app_email, app_key=app_key)))

    # pending email input (setelah pilih CHECK/DEL di tombol)
    # taruh setelah ConversationHandlers supaya tidak ganggu wizard
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, pending_email_input))

    # reminder job: cek setiap 1 jam untuk semua app
    app.job_queue.run_repeating(reminder_job_all_apps, interval=3600, first=10)

    print("Bot sedang berjalan...")
    app.run_polling()

if __name__ == "__main__":
    main()
