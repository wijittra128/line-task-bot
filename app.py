import os
import datetime
import json
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
import gspread
from google.oauth2.service_account import Credentials

app = Flask(__name__)

# --- CONFIGURATION ---
CHANNEL_ACCESS_TOKEN = os.environ.get("CHANNEL_ACCESS_TOKEN", "")
CHANNEL_SECRET = os.environ.get("CHANNEL_SECRET", "")
USER_ID = os.environ.get("USER_ID", "")
GOOGLE_SHEET_URL = os.environ.get("GOOGLE_SHEET_URL", "https://docs.google.com/spreadsheets/d/1B-m_g3rUy6_0PxwIJ2BtvDgoNX66VmX_d80-HHJt7GA/edit")
GOOGLE_CREDS_JSON = os.environ.get("GOOGLE_SHEETS_CREDS", "") # JSON string from Service Account

configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

# --- GOOGLE SHEETS SETUP ---
def get_sheet():
    if not GOOGLE_CREDS_JSON:
        return None
    try:
        creds_dict = json.loads(GOOGLE_CREDS_JSON)
        scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
        client = gspread.authorize(creds)
        return client.open_by_url(GOOGLE_SHEET_URL).sheet1
    except Exception as e:
        print(f"Error connecting to Google Sheets: {e}")
        return None

def init_sheet():
    sheet = get_sheet()
    if sheet:
        headers = ["ID", "Name", "Description", "Assignee", "Deadline", "Status", "Link", "ImageID", "CompletedAt", "CreatedAt"]
        existing_headers = sheet.row_values(1)
        if not existing_headers:
            sheet.append_row(headers)

def get_next_id(sheet):
    vals = sheet.col_values(1)
    if len(vals) <= 1: return 1
    ids = [int(v) for v in vals[1:] if v.isdigit()]
    return max(ids) + 1 if ids else 1

def format_date(date_str):
    if not date_str: return "ไม่ระบุ"
    try:
        dt = datetime.datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
        return dt.strftime("%d/%m/%Y")
    except:
        return date_str

def get_help_message():
    return ("🤖 [คู่มือ Bot จัดการงาน - Google Sheets Edition]\n"
            "--------------------------\n"
            "📝 คำสั่งหลักที่ใช้งานได้:\n\n"
            "➕ 1. พิมพ์ 👉 'สั่งงาน'\n"
            "เพื่อเริ่มบันทึกงานใหม่\n\n"
            "✅ 2. พิมพ์ 👉 'ส่งงาน'\n"
            "เพื่อปิดจ๊อบงานที่ทำเสร็จแล้ว\n\n"
            "📋 3. พิมพ์ 👉 'เช็คงาน'\n"
            "เพื่อดูกระดานสรุปงานทั้งหมด\n\n"
            "⏳ 4. พิมพ์ 👉 'เช็คงานที่ยังไม่ได้ทำ'\n"
            "🎉 5. พิมพ์ 👉 'เช็คงานที่ส่งไปแล้ว'\n"
            "❌ 6. พิมพ์ 👉 'ยกเลิก'\n"
            "📖 7. พิมพ์ 👉 'แนะนำ'\n"
            "--------------------------\n"
            "💡 ข้อมูลทั้งหมดจะถูกเก็บไว้ที่ Google Sheets ของคุณแบบเรียลไทม์จ้า!")

# --- DATABASE OPERATIONS (REPLACED WITH GOOGLE SHEETS) ---
def list_tasks_all():
    sheet = get_sheet()
    if not sheet: return "❌ ติดต่อ Google Sheets ไม่ได้จ้า!"
    records = sheet.get_all_records()
    if not records: return "📭 ยังไม่มีงานในระบบเลยจ้า!"
    
    # Sort by ID descending (latest first)
    records.sort(key=lambda x: int(x['ID']), reverse=True)
    tasks = records[:20]
    
    res = "📋 รายการงานทั้งหมด (ล่าสุด):\n"
    for t in tasks:
        status_th = "✅ ส่งงานแล้ว" if t['Status'] == 'Sent' else "⏳ ยังไม่ได้ทำ"
        res += (f"ID: {t['ID']} [{status_th}]\n"
                f"📝 งาน: {t['Description']}\n"
                f"👤 คนทำ: {t['Assignee']}\n"
                f"------------------\n")
    return res

def list_tasks_pending():
    sheet = get_sheet()
    if not sheet: return "❌ ติดต่อ Google Sheets ไม่ได้จ้า!"
    records = sheet.get_all_records()
    pending = [r for r in records if r['Status'] == 'Pending']
    if not pending: return "📭 ตอนนี้ไม่มีงานค้างจ้า ดีมากเลย!"
    
    pending.sort(key=lambda x: x['Deadline'])
    res = "⏳ เช็คงานที่ยังไม่ได้ทำ:\n"
    for t in pending:
        res += (f"ID: {t['ID']}\n"
                f"📝 งาน: {t['Description']}\n"
                f"👤 ใครทำ: {t['Assignee']}\n"
                f"📅 ส่งวันที่: {format_date(t['Deadline'])}\n"
                f"------------------\n")
    return res

def list_tasks_completed():
    sheet = get_sheet()
    if not sheet: return "❌ ติดต่อ Google Sheets ไม่ได้จ้า!"
    records = sheet.get_all_records()
    completed = [r for r in records if r['Status'] == 'Sent']
    if not completed: return "📭 ยังไม่มีงานที่ส่งแล้วจ้า!"
    
    completed.sort(key=lambda x: x['CompletedAt'], reverse=True)
    res = "🎉 เช็คงานที่ส่งไปแล้ว:\n"
    for t in completed[:20]:
        res += (f"ID: {t['ID']}\n"
                f"📝 งาน: {t['Description']}\n"
                f"👤 คนทำ: {t['Assignee']}\n"
                f"✅ ส่งเมื่อ: {format_date(t['CompletedAt'])}\n"
                f"------------------\n")
    return res

def complete_task_sheet(task_id, link=None):
    sheet = get_sheet()
    if not sheet: return None
    cell = sheet.find(str(task_id))
    if not cell or cell.col != 1: return None
    
    row = cell.row
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Update Status, Link, CompletedAt
    # Columns: ID(1), Name(2), Desc(3), Assignee(4), Deadline(5), Status(6), Link(7), ImageID(8), CompAt(9)
    sheet.update_cell(row, 6, "Sent")
    sheet.update_cell(row, 7, link if link else "")
    sheet.update_cell(row, 9, now)
    
    data = sheet.row_values(row)
    return data[2], data[3] # Description, Assignee

def send_weekly_summary():
    sheet = get_sheet()
    if not sheet: return
    records = sheet.get_all_records()
    pending = [r for r in records if r['Status'] == 'Pending']
    completed = [r for r in records if r['Status'] == 'Sent']

    summary_msg = "📊 [สรุปตารางงานประจำสัปดาห์]\n"
    summary_msg += "------------------\n"
    summary_msg += "✅ งานที่ทำเสร็จแล้ว:\n"
    if not completed:
        summary_msg += "- ยังไม่มีจ้า\n"
    else:
        for c in completed: summary_msg += f"• {c['Description']} (โดย: {c['Assignee']})\n"
            
    summary_msg += "\n⏳ งานที่ยังค้างอยู่:\n"
    if not pending:
        summary_msg += "- ไม่มีงานค้าง ดีเยี่ยม!\n"
    else:
        for p in pending: summary_msg += f"• {p['Description']}\n  └ คนทำ: {p['Assignee']} [กำหนด: {format_date(p['Deadline'])}]\n"
            
    summary_msg += "------------------\n"
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        try: line_bot_api.push_message(PushMessageRequest(to=USER_ID, messages=[TextMessage(text=summary_msg)]))
        except: pass

def check_reminders():
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sheet = get_sheet()
    if not sheet: return
    records = sheet.get_all_records()
    due_tasks = [r for r in records if r['Status'] == 'Pending' and r['Deadline'] <= now]
    
    if due_tasks:
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            for task in due_tasks:
                msg = f"🔔 [แจ้งเตือนดิวงาน!]\n📝 งาน: {task['Description']}\n👤 ใครทำ: {task['Assignee']}\n🚨 ถึงกำหนดส่งแล้วจ้า! ส่งงานหรือยัง?"
                try: line_bot_api.push_message(PushMessageRequest(to=USER_ID, messages=[TextMessage(text=msg)]))
                except: pass

# --- WEBHOOK ENDPOINT ---
@app.route("/", methods=['GET'])
def index():
    return "Bot is running with Google Sheets! 🤖📈", 200

@app.route("/callback", methods=['POST'], strict_slashes=False)
def callback():
    print(f"Request path: {request.path}")
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
    sheet = get_sheet()

    if not sheet:
        reply = "⚠️ ระบบขัดข้อง: ไม่สามารถเชื่อมต่อ Google Sheets ได้ค่ะ กรุณาตรวจสอบการตั้งค่า"
    
    # Cancellation
    elif uid in user_states and text == "ยกเลิก":
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
                
                # Check duplicate
                records = sheet.get_all_records()
                dup = next((r for r in records if r['Description'] == state["data"]["description"] and r['Assignee'] == state["data"]["assignee"] and r['Deadline'] == db_deadline), None)
                
                if dup:
                    reply = f"⚠️ สั่งงานซ้ำค่ะ! สั่งงานไปแล้ว เป็นงาน ID ที่ {dup['ID']} ค่ะ"
                else:
                    new_id = get_next_id(sheet)
                    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    # ["ID", "Name", "Description", "Assignee", "Deadline", "Status", "Link", "ImageID", "CompletedAt", "CreatedAt"]
                    sheet.append_row([new_id, state["data"]["name"], state["data"]["description"], state["data"]["assignee"], db_deadline, "Pending", "", "", "", now])
                    reply = f"✅ ลงตารางงานให้เรียบร้อยแล้วค่ะ (ID: {new_id})"
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
                cell = sheet.find(str(task_id))
                if not cell or cell.col != 1:
                    reply = f"❌ ไม่พบงาน ID: {task_id} ค่ะ กรุณาพิมพ์ใหม่:"
                else:
                    row_data = sheet.row_values(cell.row)
                    # Status is at column 6
                    status = row_data[5] if len(row_data) >= 6 else ""
                    if status == 'Sent':
                        comp_date = format_date(row_data[8]) if len(row_data) >= 9 else "ไม่ระบุ"
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
            task = complete_task_sheet(state["data"]["id"], link)
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

    if reply:
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.reply_message(ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text=reply)]))

@handler.add(MessageEvent, message=ImageMessageContent)
def handle_image(event):
    uid = event.source.user_id
    sheet = get_sheet()
    if not sheet: return

    if uid in user_states and user_states[uid].get("step") == "image":
        task_id = user_states[uid]["task_id"]
        cell = sheet.find(str(task_id))
        if cell and cell.col == 1:
            sheet.update_cell(cell.row, 8, event.message.id) # Column 8 for ImageID
            
        reply = f"🖼️ แนบรูปภาพเข้ากับ Google Sheet เรียบร้อยแล้วค่ะ! ปิดจ๊อบสมบูรณ์ ✨"
        del user_states[uid]
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.reply_message(ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text=reply)]))

# --- INITIALIZATION ---
init_sheet()
scheduler = BackgroundScheduler(timezone="Asia/Bangkok")
scheduler.add_job(check_reminders, 'interval', minutes=10) # Checked every 10 mins for Sheets to avoid rate limit
scheduler.add_job(send_weekly_summary, 'cron', day_of_week='sun', hour=18, minute=0)

if not scheduler.running:
    scheduler.start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
