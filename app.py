import os
import sqlite3
import datetime
from flask import Flask, request, abort
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    PushMessageRequest,
    TextMessage
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent, ImageMessageContent, FollowEvent
from apscheduler.schedulers.background import BackgroundScheduler

app = Flask(__name__)

# --- CONFIGURATION ---
CHANNEL_ACCESS_TOKEN = os.environ.get("CHANNEL_ACCESS_TOKEN", "oA8xcZaP7SWLLuEHaz0+H/UsobPNOocSVNihAjwUpy+aJ15F6g4VaYNwLYudXHngw0BJUFn4seGcJZ8KCuR1dH5HdPSeRPM/flcJEt1b5Xyi9IG+WC8mrUPGNzRbRWScvQh4mTQV+NNwEyPYFc7+xo9PbdgDzCFqoOLOYbqAITQ=")
CHANNEL_SECRET = os.environ.get("CHANNEL_SECRET", "bc2da170732c3c8d7b48cf93de79664b")
DB_PATH = os.environ.get("DB_PATH", "tasks.db")
USER_ID = os.environ.get("USER_ID", "U55ee1e87ca2fc1eb84215a7cb525b24b")

configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

# --- DATABASE SETUP ---
def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT DEFAULT 'ไม่มีรายละเอียด',
                assignee TEXT DEFAULT 'ไม่ระบุ',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                deadline DATETIME,
                status TEXT DEFAULT 'Pending',
                submission_link TEXT,
                submission_img_id TEXT,
                completed_at DATETIME
            )
        ''')
        cols = [c[1] for c in conn.execute("PRAGMA table_info(tasks)").fetchall()]
        if 'completed_at' not in cols:
            conn.execute("ALTER TABLE tasks ADD COLUMN completed_at DATETIME")

def get_help_message():
    return ("🤖 [คู่มือการใช้งาน Bot จัดการตารางงาน นะจ๊ะ]\n"
            "--------------------------\n"
            "📝 คำสั่งหลักที่ใช้งานได้:\n\n"
            "➕ 1. พิมพ์ 👉 'สั่งงาน'\n"
            "เพื่อเริ่มบันทึกงานใหม่ (Bot จะถามรายละเอียด, คนทำ และวันส่งงาน ทีละขั้นตอนค่ะ)\n\n"
            "✅ 2. พิมพ์ 👉 'ส่งงาน'\n"
            "เพื่อปิดจ๊อบงานที่ทำเสร็จแล้ว (Bot จะถามเลข ID งาน และให้แนบลิงก์/รูปภาพค่ะ)\n\n"
            "📋 3. พิมพ์ 👉 'เช็คงาน'\n"
            "เพื่อดูกระดานสรุปงานทั้งหมดในระบบ (บอกสถานะว่าอันไหนค้าง/อันไหนส่งแล้ว)\n\n"
            "⏳ 4. พิมพ์ 👉 'เช็คงานที่ยังไม่ได้ทำ'\n"
            "เพื่อดูเฉพาะงานที่ยังคงค้างอยู่ค่ะ\n\n"
            "🎉 5. พิมพ์ 👉 'เช็คงานที่ส่งไปแล้ว'\n"
            "เพื่อดูประวัติงานที่ทำสำเร็จแล้วค่ะ\n\n"
            "❌ 6. พิมพ์ 👉 'ยกเลิก'\n"
            "เพื่อยกเลิกการพิมพ์สั่งงาน/ส่งงานที่ค้างอยู่กลางคันค่ะ\n\n"
            "📖 7. พิมพ์ 👉 'แนะนำ'\n"
            "เพื่อเรียกดูข้อความคู่มือนี้อีกครั้งค่ะ\n"
            "--------------------------\n"
            "💡 หมายเหตุ: หากถึงวันกำหนดส่งแล้วยังไม่พิมพ์ส่งงาน Bot จะทักแจ้งเตือนอัตโนมัติ และจะส่งสรุปงานทั้งหมดให้ทุกวันอาทิตย์ 18:00 น. จ้า 💪✨")

def format_date(date_str):
    if not date_str: return "ไม่ระบุ"
    try:
        dt = datetime.datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
        return dt.strftime("%d/%m/%Y")
    except:
        return date_str

def list_tasks_all():
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute("SELECT id, description, assignee, deadline, status FROM tasks ORDER BY id DESC LIMIT 20")
        tasks = cursor.fetchall()
    if not tasks: return "📭 ยังไม่มีงานในระบบเลยจ้า!"
    res = "📋 รายการงานทั้งหมด (ล่าสุด):\n"
    for t in tasks:
        status_th = "✅ ส่งงานแล้ว" if t[4] == 'Sent' else "⏳ ยังไม่ได้ทำ"
        res += (f"ID: {t[0]} [{status_th}]\n"
                f"📝 งาน: {t[1]}\n"
                f"👤 คนทำ: {t[2]}\n"
                f"------------------\n")
    return res

def list_tasks_pending():
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute("SELECT id, description, assignee, deadline FROM tasks WHERE status = 'Pending' ORDER BY deadline")
        tasks = cursor.fetchall()
    if not tasks: return "📭 ตอนนี้ไม่มีงานค้างจ้า ดีมากเลย!"
    res = "⏳ เช็คงานที่ยังไม่ได้ทำ:\n"
    for t in tasks:
        res += (f"ID: {t[0]}\n"
                f"📝 งาน: {t[1]}\n"
                f"👤 ใครทำ: {t[2]}\n"
                f"📅 ส่งวันที่: {format_date(t[3])}\n"
                f"------------------\n")
    return res

def list_tasks_completed():
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute("SELECT id, description, assignee, completed_at FROM tasks WHERE status = 'Sent' ORDER BY completed_at DESC LIMIT 20")
        tasks = cursor.fetchall()
    if not tasks: return "📭 ยังไม่มีงานที่ส่งแล้วจ้า!"
    res = "🎉 เช็คงานที่ส่งไปแล้ว:\n"
    for t in tasks:
        res += (f"ID: {t[0]}\n"
                f"📝 งาน: {t[1]}\n"
                f"👤 คนทำ: {t[2]}\n"
                f"✅ ส่งเมื่อ: {format_date(t[3])}\n"
                f"------------------\n")
    return res

def complete_task_db(task_id, link=None):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("UPDATE tasks SET status = 'Sent', submission_link = ?, completed_at = ? WHERE id = ?", (link, now, task_id))
        cursor = conn.execute("SELECT description, assignee FROM tasks WHERE id = ?", (task_id,))
        return cursor.fetchone()

# --- WEEKLY SUMMARY & REMINDERS ---
def send_weekly_summary():
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute("SELECT description, assignee, deadline FROM tasks WHERE status = 'Pending' ORDER BY deadline")
        pending = cursor.fetchall()
        cursor = conn.execute("SELECT description, assignee FROM tasks WHERE status = 'Sent'")
        completed = cursor.fetchall()

    summary_msg = "📊 [สรุปตารางงานประจำสัปดาห์]\n"
    summary_msg += "------------------\n"
    summary_msg += "✅ งานที่ทำเสร็จแล้ว:\n"
    if not completed:
        summary_msg += "- ยังไม่มีจ้า\n"
    else:
        for c in completed: summary_msg += f"• {c[0]} (โดย: {c[1]})\n"
            
    summary_msg += "\n⏳ งานที่ยังค้างอยู่:\n"
    if not pending:
        summary_msg += "- ไม่มีงานค้าง ดีเยี่ยม!\n"
    else:
        for p in pending: summary_msg += f"• {p[0]}\n  └ คนทำ: {p[1]} [กำหนด: {format_date(p[2])}]\n"
            
    summary_msg += "------------------\n"
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        try: line_bot_api.push_message(PushMessageRequest(to=USER_ID, messages=[TextMessage(text=summary_msg)]))
        except: pass

def check_reminders():
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute("SELECT id, description, assignee FROM tasks WHERE status = 'Pending' AND deadline <= ?", (now,))
        due_tasks = cursor.fetchall()
    
    if due_tasks:
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            for task in due_tasks:
                msg = f"🔔 [แจ้งเตือนดิวงาน!]\n📝 งาน: {task[1]}\n👤 ใครทำ: {task[2]}\n🚨 ถึงกำหนดส่งแล้วจ้า! ส่งงานหรือยัง?"
                try: line_bot_api.push_message(PushMessageRequest(to=USER_ID, messages=[TextMessage(text=msg)]))
                except: pass

# --- WEBHOOK ENDPOINT ---
@app.route("/", methods=['GET'])
def index():
    return "Bot is running! 🤖", 200

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature')
    body = request.get_data(as_text=True)
    try: handler.handle(body, signature)
    except InvalidSignatureError: abort(400)
    return 'OK'

user_states = {}

@handler.add(FollowEvent)
def handle_follow(event):
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text="ยินดีต้อนรับจ้า! 😊 ทีม Graphic Taem พร้อมลุยงาน!\n\n" + get_help_message())]))

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    text = event.message.text.strip()
    uid = event.source.user_id
    reply = ""

    # Cancellation
    if uid in user_states and text == "ยกเลิก":
        del user_states[uid]
        reply = "❌ ยกเลิกการทำรายการเรียบร้อยแล้วค่ะ"

    # 1. Flow: สั่งงาน (Ordering) 
    elif uid in user_states and user_states[uid]["action"] == "creating":
        state = user_states[uid]
        step = state["step"]
        
        if step == "description":
            state["data"]["description"] = text
            state["data"]["name"] = text[:20] + "..." if len(text) > 20 else text
            state["step"] = "assignee"
            reply = "👤 ขั้นตอนที่ 2: งานนี้ใครทำคะ?\n(ตัวอย่าง: พี่หนิง, น้องเอ)"
            
        elif step == "assignee":
            state["data"]["assignee"] = text
            state["step"] = "deadline"
            reply = "📅 ขั้นตอนที่ 3: วันที่ส่งงานคือวันไหนคะ?\n(ตัวอย่าง: 05/06/2026)"
            
        elif step == "deadline":
            try:
                parsed_date = datetime.datetime.strptime(text, "%d/%m/%Y")
                db_deadline = parsed_date.replace(hour=23, minute=59, second=59).strftime("%Y-%m-%d %H:%M:%S")
                
                with sqlite3.connect(DB_PATH) as conn:
                    # Duplicate check
                    cursor = conn.execute("SELECT id FROM tasks WHERE description=? AND assignee=? AND deadline=?", 
                                          (state["data"]["description"], state["data"]["assignee"], db_deadline))
                    dup = cursor.fetchone()
                    if dup:
                        reply = f"⚠️ สั่งงานซ้ำค่ะ! สั่งงานไปแล้ว เป็นงาน ID ที่ {dup[0]} ค่ะ"
                    else:
                        conn.execute("INSERT INTO tasks (name, description, assignee, deadline) VALUES (?, ?, ?, ?)", 
                                     (state["data"]["name"], state["data"]["description"], state["data"]["assignee"], db_deadline))
                        reply = "✅ ลงตารางงานให้เรียบร้อยแล้วค่ะ"
                del user_states[uid]
            except Exception as e:
                reply = "❌ รูปแบบวันที่ไม่ถูกต้องค่ะ กรุณาพิมพ์ใหม่ (วว/ดด/ปปปป)\n(ตัวอย่าง: 05/06/2026)"

    # 2. Flow: ส่งงาน (Submitting)
    elif uid in user_states and user_states[uid]["action"] == "completing":
        state = user_states[uid]
        step = state["step"]
        
        if step == "id":
            if text.isdigit():
                task_id = int(text)
                with sqlite3.connect(DB_PATH) as conn:
                    cursor = conn.execute("SELECT status, completed_at FROM tasks WHERE id = ?", (task_id,))
                    task = cursor.fetchone()
                    if not task:
                        reply = f"❌ ไม่พบงาน ID: {task_id} ค่ะ กรุณาพิมพ์ใหม่:"
                    elif task[0] == 'Sent':
                        comp_date = format_date(task[1])
                        reply = f"⚠️ งาน ID {task_id} นี้ ส่งงานไปแล้วตั้งแต่วันที่ {comp_date} ค่ะ!"
                        del user_states[uid]
                    else:
                        state["data"]["id"] = task_id
                        state["step"] = "link"
                        reply = "🔗 ขั้นตอนที่ 2: แนบลิงก์งานค่ะ\n(ตัวอย่าง: https://canva... หรือพิมพ์ 'ไม่มี')"
            else:
                reply = "❌ กรุณาระบุเป็นตัวเลข ID เท่านั้นค่ะ (เช่น 1)"
        elif step == "link":
            link = None if text == "ไม่มี" else text
            task = complete_task_db(state["data"]["id"], link)
            if task:
                reply = f"✅ รับทราบการส่งงานค่ะ!\n📝 งาน: {task[0]}\n👤 คนส่ง: {task[1]}\n\n📸 ขั้นตอนสุดท้าย: ส่งรูปภาพงานเข้าแชทได้เลย\n(หรือพิมพ์ 'ไม่มี' เพื่อปิดจ๊อบค่ะ)"
                state["step"] = "image"
                state["task_id"] = state["data"]["id"]
        elif step == "image":
            if text == "ไม่มี" or text == "ตกลง":
                del user_states[uid]
                reply = "👌 ปิดจ๊อบงานนี้เรียบร้อยแล้วค่ะ เยี่ยมมาก!"
            else:
                reply = "📸 กรุณาส่งเป็นรูปภาพ หรือพิมพ์ว่า 'ไม่มี' ค่ะ"

    # --- DIRECT COMMANDS ---
    else:
        if text == "สั่งงาน":
            user_states[uid] = {"action": "creating", "step": "description", "data": {}}
            reply = "📝 ขั้นตอนที่ 1: ขอรายละเอียดงานค่ะ\n(ตัวอย่าง: ออกแบบปกเพจเฟซบุ๊ก โทนสีฟ้าและชมพู)"
        
        elif text == "ส่งงาน":
            user_states[uid] = {"action": "completing", "step": "id", "data": {}}
            reply = "🔢 ขั้นตอนที่ 1: ส่งงาน ID อะไรคะ?\n(ตัวอย่าง: 1)"
            
        elif text == "เช็คงานที่ยังไม่ได้ทำ":
            reply = list_tasks_pending()
            
        elif text == "เช็คงานที่ส่งไปแล้ว":
            reply = list_tasks_completed()

        elif text == "เช็คงาน":
            reply = list_tasks_all()
        
        elif text == "แนะนำ" or text.lower() == "help":
            reply = get_help_message()
            
        # SILENT FALLBACK
        else:
            pass

    if reply:
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.reply_message(ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text=reply)]))

@handler.add(MessageEvent, message=ImageMessageContent)
def handle_image(event):
    uid = event.source.user_id
    if uid in user_states and user_states[uid].get("step") == "image":
        task_id = user_states[uid]["task_id"]
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("UPDATE tasks SET submission_img_id = ? WHERE id = ?", (event.message.id, task_id))
        reply = f"🖼️ แนบรูปภาพเข้ากับตารางงานเรียบร้อยแล้วค่ะ! ปิดจ๊อบสมบูรณ์ ✨"
        del user_states[uid]
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.reply_message(ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text=reply)]))

# --- INITIALIZATION ---
init_db()
scheduler = BackgroundScheduler(timezone="Asia/Bangkok")
scheduler.add_job(check_reminders, 'interval', minutes=1)
scheduler.add_job(send_weekly_summary, 'cron', day_of_week='sun', hour=18, minute=0)

# To prevent multiple schedulers in multi-worker environments, 
# start it only if not already running.
if not scheduler.running:
    scheduler.start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
