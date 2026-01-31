from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application, CommandHandler, ContextTypes,
    MessageHandler, filters
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

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN kosong. Set Railway Variables: BOT_TOKEN=token_dari_BotFather")

# ==========================================================
# UI
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

# ==========================================================
# HELPERS
# ==========================================================
def mask_phone(p):
    p = "".join(c for c in str(p) if c.isdigit())
    return p[:4] + "****" + p[-4:] if len(p) >= 8 else p

def fmt_dt(dt): return dt.strftime("%Y-%m-%d %H:%M:%S")
def parse_dt(s): return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")

def human(td):
    s = int(td.total_seconds())
    if s <= 0: return "❌ HABIS"
    d = s // 86400
    h = (s % 86400) // 3600
    m = (s % 3600) // 60
    if d > 0: return f"{d} hari {h} jam"
    if h > 0: return f"{h} jam {m} menit"
    return f"{m} menit"

def _flag(v): return str(v).lower() in ("1","true","yes","sent","done")

# ==========================================================
# GOOGLE SHEET
# ==========================================================
def get_spreadsheet():
    if "GSHEET_CREDS_JSON" not in os.environ:
        raise RuntimeError("GSHEET_CREDS_JSON belum diset di Railway Variables")

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

# ==========================================================
# OWNER
# ==========================================================
def save_owner(cid):
    with open(OWNER_FILE, "w") as f:
        f.write(str(cid))

def load_owner():
    try:
        return int(open(OWNER_FILE).read().strip())
    except:
        return None

# ==========================================================
# COMMANDS
# ==========================================================
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤍 Angel Studyneeds Bot", reply_markup=main_menu_kb())

async def set_owner(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    save_owner(update.effective_chat.id)
    await update.message.reply_text("✅ Owner disimpan", reply_markup=main_menu_kb())

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
                exp = parse_dt(r["expire_datetime"])
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
            f"✨ {v['title']}\n"
            f"Active: {a} | Expired: {e}\n"
            f"H14: {h14} | H7: {h7} | H3: {h3} | Today: {today}\n"
        )

    await update.message.reply_text("\n".join(lines), reply_markup=main_menu_kb())

async def to_kick(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    sh = get_spreadsheet()
    now = datetime.now()
    lines = ["🧹 TO KICK\n"]

    for k, v in APPS.items():
        ws = sh.worksheet(v["sheet"])
        rows = ws.get_all_records()

        block = []
        for r in rows:
            try:
                exp = parse_dt(r["expire_datetime"])
                secs = (exp - now).total_seconds()
                if secs <= 0 or secs / 86400 <= 3:
                    block.append(f"{r['email']} | {human(exp-now)} | {mask_phone(r.get('customer_phone',''))}")
            except:
                pass

        if block:
            lines.append(f"\n✨ {v['title']}")
            lines.extend(block)

    await update.message.reply_text("\n".join(lines), reply_markup=main_menu_kb())

async def search_any(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.message.text.replace("/search", "").strip().lower()
    if not q:
        await update.message.reply_text("Pakai: /search kata", reply_markup=main_menu_kb())
        return

    sh = get_spreadsheet()
    lines = [f"🔎 SEARCH: {q}\n"]

    for k, v in APPS.items():
        ws = sh.worksheet(v["sheet"])
        rows = ws.get_all_records()
        hit = []
        for r in rows:
            try:
                if q in r["email"].lower() or q in str(r.get("customer_phone","")):
                    hit.append(f"{r['email']} | {r['expire_datetime']}")
            except:
                pass
        if hit:
            lines.append(f"\n✨ {v['title']}")
            lines.extend(hit)

    await update.message.reply_text("\n".join(lines), reply_markup=main_menu_kb())

async def extend_app(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    parts = update.message.text.split()
    if len(parts) != 4:
        await update.message.reply_text("Format: /extend <appkey> <email> <days>", reply_markup=main_menu_kb())
        return

    _, appkey, email, days = parts
    if appkey not in APPS:
        await update.message.reply_text(f"App tidak dikenal: {appkey}", reply_markup=main_menu_kb())
        return

    sh = get_spreadsheet()
    ws = sh.worksheet(APPS[appkey]["sheet"])
    rows = ws.get_all_records()

    for i, r in enumerate(rows, start=2):
        if str(r.get("email","")).lower() == email.lower():
            new_exp = parse_dt(r["expire_datetime"]) + timedelta(days=int(days))
            ws.update_cell(i, 4, fmt_dt(new_exp))
            ws.update_cell(i, 5, "ACTIVE")
            # reset flags kalau kolomnya ada
            for c in range(8, 13):
                try: ws.update_cell(i, c, "")
                except: pass
            await update.message.reply_text("✅ Extend sukses", reply_markup=main_menu_kb())
            return

    await update.message.reply_text("❌ Email tidak ditemukan", reply_markup=main_menu_kb())

async def handle_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()

    if text == MENU_ADD:
        await update.message.reply_text("➕ Tambah Akun dipilih (fitur form menyusul).", reply_markup=main_menu_kb())
    elif text == MENU_LIST:
        await dashboard(update, ctx)
    elif text == MENU_CHECK:
        await update.message.reply_text("🔎 Cek Email dipilih (fitur menyusul).", reply_markup=main_menu_kb())
    elif text == MENU_DELETE:
        await update.message.reply_text("🗑 Hapus Email Dobel dipilih (fitur menyusul).", reply_markup=main_menu_kb())
    elif text == MENU_OWNER:
        await set_owner(update, ctx)
    elif text == MENU_HELP:
        await update.message.reply_text("ℹ️ Gunakan menu di bawah.", reply_markup=main_menu_kb())
    else:
        # fallback biar user nggak merasa “dianggurin”
        await update.message.reply_text("Pilih menu ya 👇", reply_markup=main_menu_kb())

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
        rows = ws.get_all_records()
        msgs = []

        for i, r in enumerate(rows, start=2):
            try:
                exp = parse_dt(r["expire_datetime"])
                td = exp - now
                secs = td.total_seconds()

                if secs <= 0:
                    try: ws.update_cell(i, 5, "EXPIRED")
                    except: pass
                    continue

                days = secs / 86400
                dur = int(r.get("duration_days", 0))

                if dur >= BULANAN_MIN_DAYS:
                    if days <= 14 and not _flag(r.get("rem14_sent")):
                        msgs.append(f"{r['email']} H-14")
                        ws.update_cell(i, 8, "TRUE")
                    if days <= 7 and not _flag(r.get("rem7_sent")):
                        msgs.append(f"{r['email']} H-7")
                        ws.update_cell(i, 9, "TRUE")
                    if days <= 3 and not _flag(r.get("rem3_sent")):
                        msgs.append(f"{r['email']} H-3")
                        ws.update_cell(i, 10, "TRUE")
                    if days <= 1 and not _flag(r.get("rem1d_sent")):
                        msgs.append(f"{r['email']} H-1")
                        ws.update_cell(i, 12, "TRUE")
                else:
                    if secs / 3600 <= 1 and not _flag(r.get("rem1h_sent")):
                        msgs.append(f"{r['email']} H-1 JAM")
                        ws.update_cell(i, 11, "TRUE")
            except:
                pass

        if msgs:
            await ctx.bot.send_message(owner, f"🔔 {v['title']}\n" + "\n".join(msgs))

# ==========================================================
# MAIN
# ==========================================================
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("set_owner", set_owner))
    app.add_handler(CommandHandler("dashboard", dashboard))
    app.add_handler(CommandHandler("to_kick", to_kick))
    app.add_handler(CommandHandler("search", search_any))
    app.add_handler(CommandHandler("extend", extend_app))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_menu))

    app.job_queue.run_repeating(reminder_job_all_apps, interval=3600, first=10)
    app.run_polling()

if __name__ == "__main__":
    main()
