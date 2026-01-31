from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application, CommandHandler, ContextTypes,
    ConversationHandler, MessageHandler, CallbackQueryHandler, filters
)
from datetime import datetime, timedelta
import os, json, tempfile
import gspread
from google.oauth2.service_account import Credentials
from functools import partial

from apps_config import APPS, BULANAN_MIN_DAYS, REM_DAYS_14, REM_DAYS_7, REM_DAYS_3, REM_HOURS_1

# ==========================================================
# CONFIG
# ==========================================================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
SHEET_NAME = os.environ.get("SHEET_NAME", "Angel Studyneeds Sales")

TURNITIN_SHEET = "turnitin"
OWNER_FILE = os.environ.get("OWNER_FILE", "/tmp/owner_chat_id.txt")

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

def apps_inline_kb(prefix: str):
    buttons = [[InlineKeyboardButton("📚 Turnitin", callback_data=f"{prefix}:turnitin")]]
    row = []
    for k, v in APPS.items():
        row.append(InlineKeyboardButton(f"✨ {v['title']}", callback_data=f"{prefix}:{k}"))
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
def is_valid_email(e): return "@" in e and "." in e
def clean_phone(p): return "".join(c for c in str(p) if c.isdigit())
def is_valid_phone(p): return len(clean_phone(p)) >= 8
def mask_phone(p): return p[:4]+"****"+p[-4:] if len(p)>=8 else p
def fmt_dt(dt): return dt.strftime("%Y-%m-%d %H:%M:%S")
def parse_dt(s): return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
def remaining(dt): return dt - datetime.now()
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
    scopes = ["https://www.googleapis.com/auth/spreadsheets","https://www.googleapis.com/auth/drive"]
    data = json.loads(os.environ["GSHEET_CREDS_JSON"])
    fd, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd,"w") as f: json.dump(data,f)
    return gspread.authorize(
        Credentials.from_service_account_file(path, scopes=scopes)
    ).open(SHEET_NAME)

# ==========================================================
# OWNER
# ==========================================================
def save_owner(cid): open(OWNER_FILE,"w").write(str(cid))
def load_owner():
    try: return int(open(OWNER_FILE).read())
    except: return None

# ==========================================================
# COMMANDS BASIC
# ==========================================================
async def start(update, ctx):
    await update.message.reply_text("🤍 Angel Studyneeds Bot", reply_markup=main_menu_kb())

async def set_owner(update, ctx):
    save_owner(update.effective_chat.id)
    await update.message.reply_text("✅ Owner disimpan")

# ==========================================================
# DASHBOARD (1)
# ==========================================================
async def dashboard(update, ctx):
    sh = get_spreadsheet()
    now = datetime.now()
    lines = ["📊 DASHBOARD\n"]

    for k,v in APPS.items():
        ws = sh.worksheet(v["sheet"])
        rows = ws.get_all_records()
        a=e=h3=h7=h14=today=0
        for r in rows:
            try:
                exp = parse_dt(r["expire_datetime"])
                secs = (exp-now).total_seconds()
                if secs<=0: e+=1; continue
                a+=1
                d=secs/86400
                if d<=14: h14+=1
                if d<=7: h7+=1
                if d<=3: h3+=1
                if d<=0.01: today+=1
            except: pass
        lines.append(
            f"✨ {v['title']}\n"
            f"Active:{a} Expired:{e}\n"
            f"H14:{h14} H7:{h7} H3:{h3} Today:{today}\n"
        )
    await update.message.reply_text("\n".join(lines), reply_markup=main_menu_kb())

# ==========================================================
# TO KICK (3)
# ==========================================================
async def to_kick(update, ctx):
    sh = get_spreadsheet()
    now = datetime.now()
    lines = ["🧹 TO KICK\n"]
    for k,v in APPS.items():
        ws = sh.worksheet(v["sheet"])
        rows = ws.get_all_records()
        block=[]
        for r in rows:
            try:
                exp = parse_dt(r["expire_datetime"])
                secs=(exp-now).total_seconds()
                if secs<=0 or secs/86400<=3:
                    block.append(f"{r['email']} | {human(exp-now)} | {mask_phone(r['customer_phone'])}")
            except: pass
        if block:
            lines.append(f"\n✨ {v['title']}")
            lines.extend(block)
    await update.message.reply_text("\n".join(lines), reply_markup=main_menu_kb())

# ==========================================================
# SEARCH & FILTER (4)
# ==========================================================
async def search_any(update, ctx):
    q = update.message.text.replace("/search","").strip().lower()
    if not q: return
    sh=get_spreadsheet()
    lines=[f"🔎 SEARCH {q}\n"]
    for k,v in APPS.items():
        ws=sh.worksheet(v["sheet"])
        rows=ws.get_all_records()
        hit=[]
        for r in rows:
            if q in r["email"].lower() or q in str(r["customer_phone"]):
                hit.append(f"{r['email']} | {r['expire_datetime']}")
        if hit:
            lines.append(f"\n✨ {v['title']}")
            lines.extend(hit)
    await update.message.reply_text("\n".join(lines), reply_markup=main_menu_kb())

# ==========================================================
# EDIT DATA (5)
# ==========================================================
async def extend_app(update, ctx):
    _, app, email, days = update.message.text.split()
    sh=get_spreadsheet()
    ws=sh.worksheet(APPS[app]["sheet"])
    rows=ws.get_all_records()
    for i,r in enumerate(rows,start=2):
        if r["email"].lower()==email.lower():
            new_exp=parse_dt(r["expire_datetime"])+timedelta(days=int(days))
            ws.update_cell(i,4,fmt_dt(new_exp))
            ws.update_cell(i,5,"ACTIVE")
            for c in range(8,13): ws.update_cell(i,c,"")
            await update.message.reply_text("✅ Extend sukses", reply_markup=main_menu_kb())
            return

# ==========================================================
# REMINDER (2)
# ==========================================================
async def reminder_job_all_apps(ctx):
    owner=load_owner()
    if not owner: return
    sh=get_spreadsheet()
    now=datetime.now()

    for k,v in APPS.items():
        ws=sh.worksheet(v["sheet"])
        rows=ws.get_all_records()
        msgs=[]
        for i,r in enumerate(rows,start=2):
            try:
                exp=parse_dt(r["expire_datetime"])
                td=exp-now
                secs=td.total_seconds()
                if secs<=0:
                    ws.update_cell(i,5,"EXPIRED"); continue

                days=secs/86400
                if r["duration_days"]>=BULANAN_MIN_DAYS:
                    if days<=14 and not _flag(r["rem14_sent"]):
                        msgs.append(f"{r['email']} H-14")
                        ws.update_cell(i,8,"TRUE")
                    if days<=7 and not _flag(r["rem7_sent"]):
                        msgs.append(f"{r['email']} H-7")
                        ws.update_cell(i,9,"TRUE")
                    if days<=3 and not _flag(r["rem3_sent"]):
                        msgs.append(f"{r['email']} H-3")
                        ws.update_cell(i,10,"TRUE")
                    if days<=1 and not _flag(r["rem1d_sent"]):
                        msgs.append(f"{r['email']} H-1")
                        ws.update_cell(i,12,"TRUE")
                else:
                    if secs/3600<=1 and not _flag(r["rem1h_sent"]):
                        msgs.append(f"{r['email']} H-1 JAM")
                        ws.update_cell(i,11,"TRUE")
            except: pass

        if msgs:
            await ctx.bot.send_message(owner, f"🔔 {v['title']}\n"+"\n".join(msgs))

# ==========================================================
# MAIN
# ==========================================================
def main():
    app=Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start",start))
    app.add_handler(CommandHandler("set_owner",set_owner))
    app.add_handler(CommandHandler("dashboard",dashboard))
    app.add_handler(CommandHandler("to_kick",to_kick))
    app.add_handler(CommandHandler("search",search_any))
    app.add_handler(CommandHandler("extend",extend_app))

    app.job_queue.run_repeating(reminder_job_all_apps, interval=3600, first=10)

    app.run_polling()

if __name__=="__main__":
    main()
