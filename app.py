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
import google.generativeai as genai

app = Flask(__name__)

# --- CONFIGURATION ---
CHANNEL_ACCESS_TOKEN = os.environ.get("CHANNEL_ACCESS_TOKEN", "")
CHANNEL_SECRET = os.environ.get("CHANNEL_SECRET", "")
USER_ID = os.environ.get("USER_ID", "")
GOOGLE_SHEET_URL = os.environ.get("GOOGLE_SHEET_URL", "https://docs.google.com/spreadsheets/d/1B-m_g3rUy6_0PxwIJ2BtvDgoNX66VmX_d80-HHJt7GA/edit")
GOOGLE_CREDS_JSON = os.environ.get("GOOGLE_SHEETS_CREDS", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

# --- GEMINI AI SETUP ---
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel('gemini-1.5-flash')
else:
    model = None

def ask_gemini(prompt, system_instruction=""):
    if not model:
        return "⚠️ ขออภัยค่ะ ระบบ AI ยังไม่ได้ถูกตั้งค่า Key ไว้"
    try:
        full_prompt = f"{system_instruction}\n\nUser: {prompt}"
        response = model.generate_content(full_prompt)
        return response.text
    except Exception as e:
        print(f"Gemini Error: {e}")
        return "❌ ขออภัยค่ะ AI ขัดข้องชั่วคราว ลองใหม่อีกครั้งนะคะ"

# --- GOOGLE SHEETS SETUP & CACHING ---
task_cache = []
sheets_status = "Not Connected"

def get_sheet():
    global sheets_status
    if not GOOGLE_CREDS_JSON:
        sheets_status = "❌ GOOGLE_SHEETS_CREDS is empty"
        return None
    try:
        # Robust JSON extraction: Find first { and last }
        raw_json = GOOGLE_CREDS_JSON.strip()
        start_idx = raw_json.find('{')
        end_idx = raw_json.rfind('}')
        
        if start_idx == -1 or end_idx == -1:
            sheets_status = "❌ Invalid format: Could not find { or }"
            return None
            
        cleaned_json = raw_json[start_idx:end_idx+1]
        creds_dict = json.loads(cleaned_json)
        
        # Super Robust Private Key Repair
        if 'private_key' in creds_dict:
            pk = creds_dict['private_key']
            header = "-----BEGIN PRIVATE KEY-----"
            footer = "-----END PRIVATE KEY-----"
            if header in pk and footer in pk:
                try:
                    # Extract the middle part
                    inner = pk.split(header)[1].split(footer)[0]
                    # Remove ALL whitespace, newlines, and escaped newlines
                    # This handles \n, \\n, spaces, etc.
                    inner = "".join(inner.replace("\\n", "").split())
                    
                    # Reconstruct into proper 64-character line PEM format
                    lines = [inner[i:i+64] for i in range(0, len(inner), 64)]
                    repaired_pk = header + "\n" + "\n".join(lines) + "\n" + footer + "\n"
                    creds_dict['private_key'] = repaired_pk
                    print("✅ Private key repaired and formatted.")
                except Exception as e:
                    print(f"Error repairing private key: {e}")
        
        scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
        client = gspread.authorize(creds)
        sheet = client.open_by_url(GOOGLE_SHEET_URL).sheet1
        sheets_status = "✅ Connected Successfully"
        return sheet
    except json.JSONDecodeError as e:
        sheets_status = f"❌ JSON Error: {e}. Check your JSON content."
        print(f"JSON Decode Error: {e}")
        return None
    except Exception as e:
        sheets_status = f"❌ Connection Error: {e}"
        print(f"Error connecting to Sheets: {e}")
        return None

def refresh_cache():
    global task_cache
    sheet = get_sheet()
    if sheet:
        try:
            task_cache = sheet.get_all_records()
            print(f"Cache refreshed: {len(task_cache)} tasks loaded.")
        except Exception as e:
            print(f"Error fetching records: {e}")

def init_sheet():
    sheet = get_sheet()
    if sheet:
        try:
            headers = ["ID", "Name", "Description", "Assignee", "Deadline", "Status", "Link", "ImageID", "CompletedAt", "CreatedAt"]
            existing_headers = sheet.row_values(1)
            if not existing_headers:
                sheet.append_row(headers)
            refresh_cache()
        except Exception as e:
            print(f"Error initializing sheet: {e}")

def get_next_id():
    if not task_cache: return 1
    ids = [int(t['ID']) for t in task_cache if str(t['ID']).isdigit()]
    return max(ids) + 1 if ids else 1

def format_date(date_str):
    if not date_str: return "ไม่ระบุ"
    try:
        dt = datetime.datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
        return dt.strftime("%d/%m/%Y")
    except:
        return date_str

# --- AI ENHANCED FUNCTIONS ---
def get_ai_summary():
    if not task_cache: return "📭 ยังไม่มีงานในระบบเลยจ้า!"
    
    pending = [t for t in task_cache if t['Status'] == 'Pending']
    completed = [t for t in task_cache if t['Status'] == 'Sent']
    
    prompt = (f"ช่วยสรุปตารางงานนี้ให้ดูน่าอ่าน เป็นกันเอง และให้กำลังใจทีมงานหน่อยค่ะ:\n"
              f"งานที่ยังไม่ได้ทำ ({len(pending)} งาน): {json.dumps(pending, ensure_ascii=False)}\n"
              f"งานที่เสร็จแล้ว ({len(completed)} งาน): {json.dumps(completed, ensure_ascii=False)}\n"
              f"กรุณาสรุปให้กระชับ ไม่ต้องยาวมากค่ะ")
    
    return ask_gemini(prompt, "คุณคือผู้ช่วยจัดการงานอัจฉริยะ ชื่อ 'น้องกราฟิก' นิสัยน่ารัก ร่าเริง และชอบช่วยเหลือ")

# --- WEBHOOK ENDPOINT ---
@app.route("/", methods=['GET'])
def index():
    status_html = f"""
    <html>
    <head><title>Bot Status</title></head>
    <body style="font-family: sans-serif; padding: 20px;">
        <h1>Bot Status 🤖✨</h1>
        <p><b>Gemini AI:</b> {"✅ Enabled" if model else "❌ Disabled (Check GEMINI_API_KEY)"}</p>
        <p><b>Google Sheets:</b> {sheets_status}</p>
        <p><b>Tasks in Cache:</b> {len(task_cache)}</p>
        <p><b>LINE Webhook:</b> Ready at /callback</p>
        <hr>
        <p style="color: gray;"><i>If Google Sheets shows an error, check your Environment Variables in Render. Ensure GOOGLE_SHEETS_CREDS is a clean JSON string.</i></p>
    </body>
    </html>
    """
    return status_html, 200

@app.route("/callback", methods=['POST'], strict_slashes=False)
def callback():
    signature = request.headers.get('X-Line-Signature')
    body = request.get_data(as_text=True)
    
    # Debugging logs
    print(f"--- Webhook Received ---")
    print(f"Path: {request.path}")
    print(f"Signature: {signature}")
    print(f"Secret Length: {len(CHANNEL_SECRET)}")
    if CHANNEL_SECRET:
        print(f"Secret: {CHANNEL_SECRET[:4]}...{CHANNEL_SECRET[-4:]}")
    
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        print("❌ Invalid Signature Error!")
        abort(400)
    except Exception as e:
        print(f"❌ Error: {e}")
        abort(500)
    return 'OK'

user_states = {}

@handler.add(FollowEvent)
def handle_follow(event):
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        welcome_msg = "ยินดีต้อนรับจ้า! 😊 น้องกราฟิกพร้อมช่วยจัดการงานและตอบคำถามทุกอย่างแล้วนะคะ!\n\nพิมพ์ 'สั่งงาน' หรือถามอะไรน้องก็ได้เลยค่ะ"
        line_bot_api.reply_message(ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text=welcome_msg)]))

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    text = event.message.text.strip()
    uid = event.source.user_id
    reply = ""

    # Flow Control
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
            reply = "👤 ใครเป็นคนรับผิดชอบงานนี้คะ?"
        elif step == "assignee":
            state["data"]["assignee"] = text
            state["step"] = "deadline"
            reply = "📅 ส่งวันที่เท่าไหร่ดีคะ? (ตัวอย่าง: 05/06/2026)"
        elif step == "deadline":
            try:
                parsed_date = datetime.datetime.strptime(text, "%d/%m/%Y")
                db_deadline = parsed_date.replace(hour=23, minute=59, second=59).strftime("%Y-%m-%d %H:%M:%S")
                sheet = get_sheet()
                if sheet:
                    new_id = get_next_id()
                    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    sheet.append_row([new_id, state["data"]["name"], state["data"]["description"], state["data"]["assignee"], db_deadline, "Pending", "", "", "", now])
                    refresh_cache()
                    reply = f"✅ ลงตารางงานให้แล้วค่ะ! ID: {new_id}"
                del user_states[uid]
            except:
                reply = "❌ วันที่ผิดรูปแบบค่ะ (วว/ดด/ปปปป)"

    # 2. Flow: ส่งงาน
    elif uid in user_states and user_states[uid]["action"] == "completing":
        # ... (Same logic as before, but using cache and sheet update)
        state = user_states[uid]
        if state["step"] == "id":
            if text.isdigit():
                task_id = int(text)
                task = next((t for t in task_cache if int(t['ID']) == task_id), None)
                if not task:
                    reply = f"❌ ไม่พบงาน ID {task_id} ค่ะ"
                elif task['Status'] == 'Sent':
                    reply = f"⚠️ งานนี้ส่งไปแล้วค่ะ!"
                    del user_states[uid]
                else:
                    state["data"]["id"] = task_id
                    state["step"] = "link"
                    reply = "🔗 แนบลิงก์งาน (หรือพิมพ์ 'ไม่มี'):"
            else: reply = "❌ ใส่ ID เป็นตัวเลขนะคะ"
        elif state["step"] == "link":
            link = "" if text == "ไม่มี" else text
            sheet = get_sheet()
            cell = sheet.find(str(state["data"]["id"]))
            if cell:
                now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                sheet.update_cell(cell.row, 6, "Sent")
                sheet.update_cell(cell.row, 7, link)
                sheet.update_cell(cell.row, 9, now)
                refresh_cache()
                reply = "✅ ส่งงานเรียบร้อย! ส่งรูปภาพยืนยันมาได้เลยนะคะ (หรือพิมพ์ 'ไม่มี')"
                state["step"] = "image"
                state["task_id"] = state["data"]["id"]

    # --- DIRECT COMMANDS & GEMINI AI ---
    else:
        if text == "สั่งงาน":
            user_states[uid] = {"action": "creating", "step": "description", "data": {}}
            reply = "📝 ขอรายละเอียดงานหน่อยค่ะ?"
        elif text == "ส่งงาน":
            user_states[uid] = {"action": "completing", "step": "id", "data": {}}
            reply = "🔢 งาน ID อะไรคะ?"
        elif text == "เช็คงาน":
            reply = get_ai_summary() # AI summarizes tasks
        elif text == "เช็คงานดิบ": # Non-AI backup
            reply = "📋 งานทั้งหมด:\n" + "\n".join([f"- {t['ID']}: {t['Description']} ({t['Status']})" for t in task_cache[:10]])
        else:
            # ALL OTHER TEXT GOES TO GEMINI
            reply = ask_gemini(text, "คุณคือ 'น้องกราฟิก' ผู้ช่วยอัจฉริยะที่ช่วยจัดการตารางงาน และรอบรู้ทุกเรื่อง หากถูกถามเรื่องงานให้ดูข้อมูลจากตารางงานล่าสุดเสมอ แต่ถ้าถูกถามเรื่องอื่นให้ช่วยค้นหาและตอบอย่างใจดี")

    if reply:
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.reply_message(ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text=reply)]))

@handler.add(MessageEvent, message=ImageMessageContent)
def handle_image(event):
    uid = event.source.user_id
    if uid in user_states and user_states[uid].get("step") == "image":
        task_id = user_states[uid]["task_id"]
        sheet = get_sheet()
        cell = sheet.find(str(task_id))
        if cell:
            sheet.update_cell(cell.row, 8, event.message.id)
        refresh_cache()
        del user_states[uid]
        reply = "🖼️ บันทึกรูปภาพเรียบร้อย! ปิดจ๊อบสมบูรณ์จ้า ✨"
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.reply_message(ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text=reply)]))

# --- INITIALIZATION ---
init_sheet()
scheduler = BackgroundScheduler(timezone="Asia/Bangkok")
scheduler.add_job(refresh_cache, 'interval', minutes=5)
scheduler.start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
