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
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure
import certifi
import google.generativeai as genai

app = Flask(__name__)

# --- CONFIGURATION ---
CHANNEL_ACCESS_TOKEN = os.environ.get("CHANNEL_ACCESS_TOKEN", "")
CHANNEL_SECRET = os.environ.get("CHANNEL_SECRET", "")
USER_ID = os.environ.get("USER_ID", "")
MONGO_URI = os.environ.get("MONGO_URI", "")
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

# --- MONGODB SETUP & CACHING ---
task_cache = []
db_status = "Not Connected"
collection = None

def init_db():
    global db_status, collection
    if not MONGO_URI:
        db_status = "❌ MONGO_URI is empty"
        return False
    try:
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000, tlsCAFile=certifi.where())
        # Check connection
        client.admin.command('ping')
        db = client['task_bot_db']
        collection = db['tasks']
        db_status = "✅ Connected Successfully to MongoDB"
        refresh_cache()
        return True
    except ConnectionFailure as e:
        db_status = f"❌ Connection Error: {e}"
        print(f"MongoDB Connection Error: {e}")
        collection = None
        return False
    except Exception as e:
        db_status = f"❌ Error: {e}"
        print(f"MongoDB Error: {e}")
        collection = None
        return False

def refresh_cache():
    global task_cache
    if collection is not None:
        try:
            # Exclude MongoDB's internal _id from cache to keep it clean
            tasks = list(collection.find({}, {'_id': False}))
            task_cache = tasks
            print(f"Cache refreshed: {len(task_cache)} tasks loaded from MongoDB.")
        except Exception as e:
            print(f"Error fetching records from MongoDB: {e}")

def get_next_id():
    if not task_cache: return 1
    ids = [int(t['ID']) for t in task_cache if str(t['ID']).isdigit()]
    return max(ids) + 1 if ids else 1

def get_help_message():
    return ("🤖 [คู่มือการใช้งานน้องกราฟิก นะจ๊ะ]\n"
            "--------------------------\n"
            "📝 คำสั่งหลักที่ใช้งานได้:\n\n"
            "➕ 1. พิมพ์ 👉 'สั่งงาน'\n"
            "เพื่อเริ่มบันทึกงานใหม่ (น้องจะถามรายละเอียดทีละขั้นตอนค่ะ)\n\n"
            "✅ 2. พิมพ์ 👉 'ส่งงาน'\n"
            "เพื่อปิดจ๊อบงานที่ทำเสร็จแล้ว (ระบุ ID งานและแนบลิงก์/รูปภาพค่ะ)\n\n"
            "📋 3. พิมพ์ 👉 'เช็คงาน'\n"
            "เพื่อให้น้องใช้ AI สรุปงานทั้งหมดในระบบให้ฟังแบบน่ารักๆ ค่ะ\n\n"
            "⏳ 4. พิมพ์ 👉 'เช็คงานดิบ'\n"
            "เพื่อดูรายการงานแบบดั้งเดิม (ID และสถานะ)\n\n"
            "📖 5. พิมพ์ 👉 'แนะนำ'\n"
            "เพื่อเรียกดูข้อความคู่มือนี้อีกครั้งค่ะ\n"
            "--------------------------\n"
            "💡 นอกจากคำสั่งข้างต้นแล้ว คุณสามารถ 'พิมพ์คุยกับน้อง' ได้ทุกเรื่องเลยนะคะ! น้องจะใช้ AI ช่วยหาคำตอบให้ค่ะ ✨")

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
    
    pending = [t for t in task_cache if t.get('Status') == 'Pending']
    completed = [t for t in task_cache if t.get('Status') == 'Sent']
    
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
        <p><b>MongoDB:</b> {db_status}</p>
        <p><b>Tasks in Cache:</b> {len(task_cache)}</p>
        <p><b>LINE Webhook:</b> Ready at /callback</p>
        <hr>
        <p style="color: gray;"><i>Ensure MONGO_URI is set correctly in your Render Environment Variables.</i></p>
    </body>
    </html>
    """
    return status_html, 200

@app.route("/callback", methods=['POST'], strict_slashes=False)
def callback():
    signature = request.headers.get('X-Line-Signature')
    body = request.get_data(as_text=True)
    
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
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
    if uid in user_states and (text == "ยกเลิก" or text == "รีเซ็ต"):
        del user_states[uid]
        reply = "❌ ยกเลิกและรีเซ็ตการทำรายการเรียบร้อยแล้วค่ะ เริ่มต้นใหม่ได้เลย!"

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
                
                if collection is not None:
                    new_id = get_next_id()
                    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    
                    new_task = {
                        "ID": new_id,
                        "Name": state["data"]["name"],
                        "Description": state["data"]["description"],
                        "Assignee": state["data"]["assignee"],
                        "Deadline": db_deadline,
                        "Status": "Pending",
                        "Link": "",
                        "ImageID": "",
                        "CompletedAt": "",
                        "CreatedAt": now
                    }
                    
                    collection.insert_one(new_task)
                    refresh_cache()
                    reply = f"✅ ลงตารางงานให้แล้วค่ะ! ID: {new_id}"
                else:
                    reply = "❌ ระบบฐานข้อมูล MongoDB ขัดข้องค่ะ ไม่สามารถบันทึกงานได้"
                del user_states[uid]
            except Exception as e:
                print(f"Error creating task: {e}")
                reply = "❌ วันที่ผิดรูปแบบค่ะ (วว/ดด/ปปปป)"

    # 2. Flow: ส่งงาน
    elif uid in user_states and user_states[uid]["action"] == "completing":
        state = user_states[uid]
        if state["step"] == "id":
            if text.isdigit():
                task_id = int(text)
                task = next((t for t in task_cache if int(t.get('ID', 0)) == task_id), None)
                if not task:
                    reply = f"❌ ไม่พบงาน ID {task_id} ค่ะ"
                elif task.get('Status') == 'Sent':
                    reply = f"⚠️ งานนี้ส่งไปแล้วค่ะ!"
                    del user_states[uid]
                else:
                    state["data"]["id"] = task_id
                    state["step"] = "link"
                    reply = "🔗 แนบลิงก์งาน (หรือพิมพ์ 'ไม่มี'):"
            else: reply = "❌ ใส่ ID เป็นตัวเลขนะคะ"
        elif state["step"] == "link":
            link = "" if text == "ไม่มี" else text
            
            if collection is not None:
                now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                task_id = state["data"]["id"]
                
                # Update in MongoDB
                collection.update_one(
                    {"ID": task_id},
                    {"$set": {"Status": "Sent", "Link": link, "CompletedAt": now}}
                )
                
                refresh_cache()
                reply = "✅ ส่งงานเรียบร้อย! ส่งรูปภาพยืนยันมาได้เลยนะคะ (หรือพิมพ์ 'ไม่มี')"
                state["step"] = "image"
                state["task_id"] = task_id
            else:
                reply = "❌ ระบบฐานข้อมูล MongoDB ขัดข้องค่ะ"
                del user_states[uid]

    # --- DIRECT COMMANDS & GEMINI AI ---
    else:
        if text == "สั่งงาน":
            user_states[uid] = {"action": "creating", "step": "description", "data": {}}
            reply = "📝 ขอรายละเอียดงานหน่อยค่ะ?"
        elif text == "ส่งงาน":
            user_states[uid] = {"action": "completing", "step": "id", "data": {}}
            reply = "🔢 งาน ID อะไรคะ?"
        elif text == "เช็คงาน":
            reply = get_ai_summary()
        elif text == "เช็คงานดิบ":
            if task_cache:
                reply = "📋 งานทั้งหมด:\n" + "\n".join([f"- {t.get('ID')}: {t.get('Description')} ({t.get('Status')})" for t in task_cache[:10]])
            else:
                reply = "📭 ยังไม่มีงานในระบบค่ะ"
        elif text == "แนะนำ" or text.lower() == "help":
            reply = get_help_message()
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
        
        if collection is not None:
            collection.update_one(
                {"ID": task_id},
                {"$set": {"ImageID": event.message.id}}
            )
            refresh_cache()
            reply = "🖼️ บันทึกรูปภาพเรียบร้อย! ปิดจ๊อบสมบูรณ์จ้า ✨"
        else:
            reply = "❌ ไม่สามารถบันทึกรูปภาพได้เนื่องจากฐานข้อมูลขัดข้อง"
            
        del user_states[uid]
        
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.reply_message(ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text=reply)]))

# --- INITIALIZATION ---
init_db()
scheduler = BackgroundScheduler(timezone="Asia/Bangkok")
scheduler.add_job(refresh_cache, 'interval', minutes=5)
scheduler.start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
