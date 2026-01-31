from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from datetime import datetime, timedelta
import os
import json
import tempfile
import gspread
from google.oauth2.service_account import Credentials

# =====================
# KONFIGURASI (AMAN UNTUK RAILWAY)
# =====================
# WAJIB di Railway Variables:
# BOT_TOKEN = 8595619697:AAGKwfFfiStWb_eQNDxbzf8FCEByj_WGuX0
# GSHEET_CREDS_JSON = isi full JSON service account (copy-paste)
# (opsional) SHEET_NAME kalau beda
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
SHEET_NAME = os.environ.get("SHEET_NAME", "Angel Studyneeds Sales")

# Tab names
SALES_SHEET = "sales"
TURNITIN_SHEET = "turnitin"
CANVA_SHEET = "canva"

# Railway filesystem itu tidak permanen, jadi simpan owner di /tmp
OWNER_FILE = os.environ.get("OWNER_FILE", "/tmp/owner_chat_id.txt")

# Reminder rules (sesuai request kamu)
BULANAN_MIN_DAYS = 28
REM_DAYS_14 = 14
REM_DAYS_7 = 7
REM_DAYS_3 = 3
REM_HOURS_1 = 1

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

    # buat file json sementara
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

def mask_phone(phone: str) -> str:
    p = str(phone or "").strip()
    if len(p) <= 6:
        return p
    return p[:4] + "****" + p[-4:]

# =====================
# TIME HELPERS
# =====================
def parse_expire_datetime(s: str) -> datetime:
    # format yang kita simpan: "YYYY-MM-DD HH:MM:SS"
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

# =====================
# COMMANDS - BASIC
# =====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Halo 👋\n"
        "Aku angel-studyneeds-bot 🤍\n\n"
        "Perintah utama:\n"
        "/set_owner → set chat kamu untuk reminder otomatis\n\n"
        "Turnitin:\n"
        "/add_tii email | durasi_hari | no_hp\n"
        "/cek_tii\n"
        "/cek_email email\n\n"
        "Canva:\n"
        "/add_canva email | durasi_hari | no_hp\n"
        "/cek_canva\n"
        "/cek_canva_email email\n"
        "/canva_hampir_habis (opsional)\n"
    )

async def set_owner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    save_owner_chat_id(chat_id)
    await update.message.reply_text("✅ Owner tersimpan. Reminder otomatis akan dikirim ke chat ini.")

async def test_sheet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        sh = get_spreadsheet()
        ws = sh.worksheet(SALES_SHEET)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ws.append_row([now, "test", "TEST", "TEST", 1, 0, 0, "-", "OK", "tes koneksi"])
        await update.message.reply_text("✅ Berhasil nulis ke Google Sheet!")
    except Exception as e:
        await update.message.reply_text(f"❌ Gagal konek ke Sheet:\n{e}")

# =====================
# TURNITIN
# =====================
def days_left(expire_str: str) -> int:
    expire_dt = datetime.strptime(expire_str, "%Y-%m-%d")
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    return (expire_dt - today).days

async def add_tii(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        text = update.message.text
        data = text.replace("/add_tii", "").strip()
        parts = [p.strip() for p in data.split("|")]

        if len(parts) != 3:
            await update.message.reply_text(
                "❌ Format salah.\n"
                "Pakai:\n"
                "/add_tii email | durasi_hari | no_hp\n\n"
                "Contoh:\n"
                "/add_tii contoh@gmail.com | 30 | 081234567890"
            )
            return

        email, duration, phone = parts
        duration = int(duration)

        now_dt = datetime.now()
        now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")
        expire_dt = now_dt + timedelta(days=duration)
        expire_str = expire_dt.strftime("%Y-%m-%d")

        sh = get_spreadsheet()
        ws = sh.worksheet(TURNITIN_SHEET)

        ws.append_row([now_str, email, duration, expire_str, "ACTIVE", phone, ""])

        await update.message.reply_text(
            f"✅ Akun Turnitin tersimpan!\n"
            f"Email: {email}\n"
            f"Durasi: {duration} hari\n"
            f"Expire: {expire_str}\n"
            f"HP: {phone}"
        )
    except ValueError:
        await update.message.reply_text("❌ Durasi harus angka (hari). Contoh: 30")
    except Exception as e:
        await update.message.reply_text(f"❌ Error:\n{e}")

async def cek_tii(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        sh = get_spreadsheet()
        ws = sh.worksheet(TURNITIN_SHEET)
        rows = ws.get_all_records()

        if not rows:
            await update.message.reply_text("Belum ada data Turnitin.")
            return

        rows = rows[-15:]
        lines = ["📄 Daftar Turnitin (15 terakhir):\n"]

        for i, r in enumerate(reversed(rows), start=1):
            email = str(r.get("email", "")).strip()
            expire = str(r.get("expire_date", "")).strip()
            phone = str(r.get("customer_phone", "")).strip()
            status = str(r.get("status", "")).strip() or "UNKNOWN"

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

        await update.message.reply_text("\n\n".join(lines))
    except Exception as e:
        await update.message.reply_text(f"❌ Error:\n{e}")

async def cek_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        text = update.message.text
        email_query = text.replace("/cek_email", "").strip()
        if not email_query:
            await update.message.reply_text("❌ Format: /cek_email email@domain.com")
            return

        sh = get_spreadsheet()
        ws = sh.worksheet(TURNITIN_SHEET)
        rows = ws.get_all_records()

        found = None
        for r in rows:
            if str(r.get("email", "")).strip().lower() == email_query.lower():
                found = r

        if not found:
            await update.message.reply_text("❌ Email tidak ditemukan di data Turnitin.")
            return

        email = str(found.get("email", "")).strip()
        expire = str(found.get("expire_date", "")).strip()
        phone = str(found.get("customer_phone", "")).strip()
        status = str(found.get("status", "")).strip() or "UNKNOWN"
        start = str(found.get("timestamp", "")).strip()
        duration = str(found.get("duration_days", "")).strip()

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

        await update.message.reply_text(
            f"📧 {email}\n"
            f"Mulai: {start}\n"
            f"Durasi: {duration} hari\n"
            f"Expire: {expire}\n"
            f"{info}\n"
            f"HP: {mask_phone(phone)}\n"
            f"Status: {status}"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Error:\n{e}")

# =====================
# CANVA
# =====================
async def add_canva(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /add_canva email | durasi_hari | no_hp
    Simpan expire_datetime dengan jam yang sama seperti waktu input.
    """
    try:
        text = update.message.text
        data = text.replace("/add_canva", "").strip()
        parts = [p.strip() for p in data.split("|")]

        if len(parts) != 3:
            await update.message.reply_text(
                "❌ Format salah.\n"
                "Pakai:\n"
                "/add_canva email | durasi_hari | no_hp\n\n"
                "Contoh:\n"
                "/add_canva contoh@gmail.com | 30 | 081234567890"
            )
            return

        email, duration, phone = parts
        duration = int(duration)

        now_dt = datetime.now()
        expire_dt = now_dt + timedelta(days=duration)

        sh = get_spreadsheet()
        ws = sh.worksheet(CANVA_SHEET)

        ws.append_row([
            fmt_dt(now_dt),
            email,
            duration,
            fmt_dt(expire_dt),
            "ACTIVE",
            phone,
            "",
            "", "", "", ""
        ])

        await update.message.reply_text(
            f"✅ Canva tersimpan!\n"
            f"Email: {email}\n"
            f"Durasi: {duration} hari\n"
            f"Expire: {fmt_dt(expire_dt)}\n"
            f"HP: {phone}"
        )

    except ValueError:
        await update.message.reply_text("❌ Durasi harus angka (hari). Contoh: 30")
    except Exception as e:
        await update.message.reply_text(f"❌ Error:\n{e}")

async def cek_canva(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        sh = get_spreadsheet()
        ws = sh.worksheet(CANVA_SHEET)
        rows = ws.get_all_records()

        if not rows:
            await update.message.reply_text("Belum ada data Canva.")
            return

        rows = rows[-15:]
        lines = ["📄 Daftar Canva (15 terakhir):\n"]

        for i, r in enumerate(reversed(rows), start=1):
            email = str(r.get("email", "")).strip()
            exp_str = str(r.get("expire_datetime", "")).strip()
            phone = str(r.get("customer_phone", "")).strip()
            status = str(r.get("status", "")).strip() or "UNKNOWN"

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

        await update.message.reply_text("\n\n".join(lines))
    except Exception as e:
        await update.message.reply_text(f"❌ Error:\n{e}")

async def cek_canva_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        text = update.message.text
        email_query = text.replace("/cek_canva_email", "").strip()
        if not email_query:
            await update.message.reply_text("❌ Format: /cek_canva_email email@domain.com")
            return

        sh = get_spreadsheet()
        ws = sh.worksheet(CANVA_SHEET)
        rows = ws.get_all_records()

        found = None
        for r in rows:
            if str(r.get("email", "")).strip().lower() == email_query.lower():
                found = r

        if not found:
            await update.message.reply_text("❌ Email tidak ditemukan di data Canva.")
            return

        email = str(found.get("email", "")).strip()
        exp_str = str(found.get("expire_datetime", "")).strip()
        phone = str(found.get("customer_phone", "")).strip()
        status = str(found.get("status", "")).strip() or "UNKNOWN"
        start = str(found.get("timestamp", "")).strip()
        duration = str(found.get("duration_days", "")).strip()

        if exp_str:
            exp_dt = parse_expire_datetime(exp_str)
            td = remaining(exp_dt)
            info = human_remaining(td)
            if td.total_seconds() <= 0:
                status = "EXPIRED"
        else:
            info = "⚠️ expire tidak ada"

        await update.message.reply_text(
            f"📧 {email}\n"
            f"Mulai: {start}\n"
            f"Durasi: {duration} hari\n"
            f"Expire: {exp_str}\n"
            f"{info}\n"
            f"HP: {mask_phone(phone)}\n"
            f"Status: {status}"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Error:\n{e}")

async def canva_hampir_habis(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        threshold_days = 3
        parts = update.message.text.strip().split()
        if len(parts) == 2:
            threshold_days = int(parts[1])

        sh = get_spreadsheet()
        ws = sh.worksheet(CANVA_SHEET)
        rows = ws.get_all_records()

        hasil = []
        for r in rows:
            email = str(r.get("email", "")).strip()
            exp_str = str(r.get("expire_datetime", "")).strip()
            phone = str(r.get("customer_phone", "")).strip()
            if not email or not exp_str:
                continue
            exp_dt = parse_expire_datetime(exp_str)
            td = remaining(exp_dt)
            days = td.total_seconds() / 86400
            if days <= threshold_days:
                hasil.append((td.total_seconds(), email, exp_str, phone))

        if not hasil:
            await update.message.reply_text(f"✅ Tidak ada Canva yang sisa ≤ {threshold_days} hari.")
            return

        hasil.sort(key=lambda x: x[0])
        lines = [f"⚠️ Canva sisa ≤ {threshold_days} hari:\n"]
        for i, (sec, email, exp_str, phone) in enumerate(hasil[:20], start=1):
            td = timedelta(seconds=int(sec))
            lines.append(
                f"{i}) {email}\n"
                f"   {human_remaining(td)} | Exp: {exp_str}\n"
                f"   HP: {mask_phone(phone)}"
            )

        await update.message.reply_text("\n\n".join(lines))

    except ValueError:
        await update.message.reply_text("❌ Contoh: /canva_hampir_habis 7")
    except Exception as e:
        await update.message.reply_text(f"❌ Error:\n{e}")

# =====================
# REMINDER JOB (OTOMATIS)
# =====================
def _flag_is_sent(v) -> bool:
    s = str(v or "").strip().lower()
    return s in ("true", "yes", "1", "sent", "done")

async def reminder_job(context: ContextTypes.DEFAULT_TYPE):
    owner_chat_id = load_owner_chat_id()
    if not owner_chat_id:
        return

    try:
        sh = get_spreadsheet()
        ws = sh.worksheet(CANVA_SHEET)
        rows = ws.get_all_records()

        if not rows:
            return

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

            if secs <= 0:
                if str(r.get("status", "")).strip().upper() != "EXPIRED":
                    ws.update_cell(idx, 5, "EXPIRED")
                continue

            if duration_days >= BULANAN_MIN_DAYS:
                days_left_float = secs / 86400.0

                rem14_sent = _flag_is_sent(r.get("rem14_sent", ""))
                rem7_sent = _flag_is_sent(r.get("rem7_sent", ""))
                rem3_sent = _flag_is_sent(r.get("rem3_sent", ""))

                if (days_left_float <= REM_DAYS_14) and (not rem14_sent):
                    remind_msgs.append(f"🔔 Canva 14 hari lagi\n{email}\nExp: {exp_str}\nHP: {mask_phone(phone)}")
                    ws.update_cell(idx, 8, "TRUE")

                if (days_left_float <= REM_DAYS_7) and (not rem7_sent):
                    remind_msgs.append(f"🔔 Canva 7 hari lagi\n{email}\nExp: {exp_str}\nHP: {mask_phone(phone)}")
                    ws.update_cell(idx, 9, "TRUE")

                if (days_left_float <= REM_DAYS_3) and (not rem3_sent):
                    remind_msgs.append(f"⚠️ Canva H-3 (siap-siap kick)\n{email}\nExp: {exp_str}\nHP: {mask_phone(phone)}")
                    ws.update_cell(idx, 10, "TRUE")

            elif duration_days < 7:
                rem1h_sent = _flag_is_sent(r.get("rem1h_sent", ""))
                hours_left = secs / 3600.0

                if (hours_left <= REM_HOURS_1) and (hours_left > 0) and (not rem1h_sent):
                    remind_msgs.append(
                        f"⏰ Canva H-1 JAM (waktunya kick kalau habis)\n"
                        f"{email}\nExp: {exp_str}\nSisa: {human_remaining(td)}\nHP: {mask_phone(phone)}"
                    )
                    ws.update_cell(idx, 11, "TRUE")

        if remind_msgs:
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
    app.add_handler(CommandHandler("set_owner", set_owner))
    app.add_handler(CommandHandler("test_sheet", test_sheet))

    # turnitin
    app.add_handler(CommandHandler("add_tii", add_tii))
    app.add_handler(CommandHandler("cek_tii", cek_tii))
    app.add_handler(CommandHandler("cek_email", cek_email))

    # canva
    app.add_handler(CommandHandler("add_canva", add_canva))
    app.add_handler(CommandHandler("cek_canva", cek_canva))
    app.add_handler(CommandHandler("cek_canva_email", cek_canva_email))
    app.add_handler(CommandHandler("canva_hampir_habis", canva_hampir_habis))

    # reminder job: cek setiap 1 jam
    # (akan jalan jika python-telegram-bot[job-queue] terinstall)
    app.job_queue.run_repeating(reminder_job, interval=3600, first=10)

    print("Bot sedang berjalan...")
    app.run_polling()

if __name__ == "__main__":
    main()
