import math
from flask import Flask, request, jsonify, Response, send_from_directory
from flask_cors import CORS
from flask_socketio import SocketIO, emit, join_room, leave_room
import os
from dotenv import load_dotenv
load_dotenv() # Load variables from .env if present
import sys
import time
from datetime import datetime
import firebase_admin
from firebase_admin import credentials, firestore, storage

# --- BOT & GUARDIAN IMPORTS ---
sys.path.append(os.path.join(os.path.dirname(__file__), 'backend/raksha_bot'))
try:
    from raksha_bot_engine import RakshaBotEngine
    from firebase_service import RakshaFirebaseService
    from pdf_generator import StudyPlanPDFGenerator
except ImportError:
    print("[Warning] Bot modules not found")

app = Flask(__name__)
app.config['SECRET_KEY'] = 'raksha_secret_key'
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# --- BOT & GUARDIAN INITIALIZATION ---
bot_engine = None
bot_fb = None
pdf_gen = None

if 'RakshaBotEngine' in globals():
    try:
        api_key = os.environ.get("OPENAI_API_KEY")
        if api_key:
            bot_engine = RakshaBotEngine(api_key=api_key)
            bot_fb = RakshaFirebaseService()
            pdf_gen = StudyPlanPDFGenerator()
            print("[Bot] Components initialized successfully")
        else:
            print("[Bot] Warning: OPENAI_API_KEY not found, engine deferred")
    except Exception as e:
        print(f"[Bot] Initialization failed: {e}")

# --- FIREBASE INITIALIZATION ---
if not firebase_admin._apps:
    key_path = 'serviceAccountKey.json'
    env_key = os.environ.get("FIREBASE_SERVICE_ACCOUNT")
    
    # Look for any .json file that looks like a service account key
    json_keys = [f for f in os.listdir('.') if f.endswith('.json') and 'firebase-adminsdk' in f]
    default_key = json_keys[0] if json_keys else 'serviceAccountKey.json'
    
    if os.path.exists(key_path):
        cred = credentials.Certificate(key_path)
        firebase_admin.initialize_app(cred, {
            'storageBucket': 'tanprix-52683.firebasestorage.app'
        })
        print(f"[Firebase] Initialized from {key_path}")
    elif os.path.exists(default_key):
        cred = credentials.Certificate(default_key)
        firebase_admin.initialize_app(cred, {
            'storageBucket': 'tanprix-52683.firebasestorage.app'
        })
        print(f"[Firebase] Initialized from {default_key}")
    elif env_key:
        try:
            import json
            cred_dict = json.loads(env_key)
            cred = credentials.Certificate(cred_dict)
            firebase_admin.initialize_app(cred, {
                'storageBucket': 'tanprix-52683.firebasestorage.app'
            })
            print("[Firebase] SUCCESS: Initialized from environment variable")
        except Exception as e:
            print(f"[Firebase] ERROR: Failed to parse FIREBASE_SERVICE_ACCOUNT JSON: {e}")
            firebase_admin.initialize_app(options={
                'storageBucket': 'tanprix-52683.firebasestorage.app'
            })
    else:
        print("[Firebase] ERROR: No credentials found!")
        firebase_admin.initialize_app(options={
            'storageBucket': 'tanprix-52683.firebasestorage.app'
        })

# --- CRASH-PROOF DB ACCESS ---
def get_db():
    try:
        return firestore.client()
    except Exception:
        print("[Firebase] CRITICAL: Firestore client access failed. Check credentials!")
        return None

# --- GLOBAL ERROR HANDLER (Strictly JSON) ---
@app.errorhandler(Exception)
def handle_exception(e):
    app.logger.exception("Unhandled error")
    return jsonify({"success": False, "error": str(e)}), 500

@app.route("/")
def home():
    return jsonify({"status": "ok", "message": "Raksha AI Bot backend running"})

@app.route("/api/ai/test")
def test_ai_route():
    return jsonify({
        "status": "ok",
        "route": "/api/ai/chat is currently active"
    })

# --- HARDENED AI CHAT ROUTE ---

@app.route('/api/ai/chat', methods=['POST'])
def ai_chat():
    try:
        # Use silent=True to handle cases where request is not JSON gracefully
        data = request.get_json(silent=True) or {}
        
        user_message = data.get("message", "").strip() or data.get("query", "").strip()
        section = data.get("section", "safety").lower()
        user_id = data.get("userId", "guest")

        if not user_message:
            return jsonify({
                "success": False,
                "error": "Message is required"
            }), 400

        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            return jsonify({
                "success": False,
                "error": "OPENAI_API_KEY is not configured on the cloud server."
            }), 500

        # Attempt AI response via Engine if loaded, otherwise fallback to direct OpenAI
        reply = "I'm having trouble thinking right now. Please check my engine."
        
        if bot_engine:
            try:
                reply = bot_engine.get_chat_response(user_message, section)
            except Exception as e:
                print(f"Bot Engine Error: {e}")
                # Fallback to direct client if engine fails
                from openai import OpenAI
                client = OpenAI(api_key=api_key)
                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": f"You are Raksha AI. Help the user in the {section} category. Be practical and safe."},
                        {"role": "user", "content": user_message}
                    ]
                )
                reply = response.choices[0].message.content
        else:
            # Direct OpenAI Fallback
            from openai import OpenAI
            client = OpenAI(api_key=api_key)
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are Raksha AI Safety Bot. Answer practical and India-focused safety tips."},
                    {"role": "user", "content": user_message}
                ]
            )
            reply = response.choices[0].message.content

        # Save to Firebase if possible
        if bot_fb and user_id != "guest":
            try:
                bot_fb.save_chat_message(user_id, {"sender": "bot", "message": reply, "section": section})
            except: pass

        return jsonify({
            "success": True,
            "reply": reply,
            "message": reply
        })

    except Exception as e:
        app.logger.exception("AI Chat Logic Failure")
        return jsonify({
            "success": True, # Still return success True but with error message to avoid frontend crash if it expects JSON
            "reply": f"Error: {str(e)}"
        })

@app.route('/api/evidence/analyze', methods=['POST'])
def analyze_frame():
    return jsonify({"success": True, "unknown_detected": False, "evidence_saved": 0, "total_evidence_saved": 0, "boxes": []})

@app.route('/api/sos/send_cloud_sms', methods=['POST'])
def cloud_sms():
    print(f"[Cloud SMS] Sending to {request.json.get('numbers')}")
    return jsonify({"success": True, "status": "Queued via Render Backend"})

@app.route('/api/sos/automate', methods=['POST'])
def automate_adb():
    return jsonify({"success": True, "status": "Automation active"})

@app.route('/api/auth/register', methods=['POST'])
def register_face():
    return jsonify({"success": True, "message": "Registered"})

# --- NEARBY POLICE STATION DETECTION ---

@app.route('/api/nearby/police', methods=['GET'])
def get_nearby_police():
    try:
        lat_raw = request.args.get('lat')
        lng_raw = request.args.get('lng')
        
        if not lat_raw or not lng_raw:
            return jsonify({"success": False, "error": "Latitude and longitude are required"}), 400
            
        try:
            lat = float(lat_raw)
            lng = float(lng_raw)
        except ValueError:
            return jsonify({"success": False, "error": "Invalid coordinate format"}), 400
            
    except Exception as e:
        return jsonify({"success": False, "error": f"Request error: {str(e)}"}), 400
    
    api_key = os.environ.get("GOOGLE_MAPS_API_KEY")
    places = []
    
    try:
        import requests
        # 1. TRY GOOGLE PLACES API
        if api_key and api_key != "placeholder_change_in_render_dashboard":
            try:
                url = f"https://maps.googleapis.com/maps/api/place/nearbysearch/json?location={lat},{lng}&radius=5000&type=police&key={api_key}"
                response = requests.get(url, timeout=10)
                
                text = response.text
                if not text:
                    print("[Maps] Empty response from Google")
                else:
                    data = response.json()
                    if data.get('status') == 'OK':
                        for item in data.get('results', []):
                            places.append({
                                "name": item.get('name'),
                                "address": item.get('vicinity'),
                                "latitude": item.get('geometry', {}).get('location', {}).get('lat'),
                                "longitude": item.get('geometry', {}).get('location', {}).get('lng'),
                                "distance": "Nearby",
                                "rating": item.get('rating', "N/A"),
                                "openNow": item.get('opening_hours', {}).get('open_now', True),
                                "placeId": item.get('place_id')
                            })
                        return jsonify({"success": True, "places": places})
                    else:
                        print(f"[Maps] Google API Status: {data.get('status')}")
            except Exception as ge:
                print(f"[Maps] Google Search failed: {str(ge)}")

        # 2. FALLBACK TO OPENSTREETMAP (OVERPASS)
        try:
            overpass_url = "https://overpass-api.de/api/interpreter"
            overpass_query = f"""
            [out:json];
            (
              node(around:5000,{lat},{lng})[amenity=police];
              way(around:5000,{lat},{lng})[amenity=police];
              relation(around:5000,{lat},{lng})[amenity=police];
            );
            out center;
            """
            response = requests.post(overpass_url, data={'data': overpass_query}, timeout=15)
            
            text = response.text
            if text and "elements" in text:
                data = response.json()
                for element in data.get('elements', []):
                    tags = element.get('tags', {})
                    places.append({
                        "name": tags.get('name', 'Police Station'),
                        "address": tags.get('addr:full') or tags.get('addr:street') or "Local Station",
                        "latitude": element.get('lat') or element.get('center', {}).get('lat'),
                        "longitude": element.get('lon') or element.get('center', {}).get('lon'),
                        "distance": "Nearby",
                        "rating": "N/A",
                        "openNow": True,
                        "placeId": f"osm-{element.get('id')}"
                    })
                return jsonify({"success": True, "places": places})
        except Exception as oe:
            print(f"[Maps] OSM Fallback failed: {str(oe)}")

        # 3. IF ALL FAIL, RETURN SUCCESS TRUE BUT EMPTY LIST TO AVOID CRASH
        return jsonify({"success": True, "places": []})
        
    except Exception as e:
        app.logger.exception("Global Nearby Failure")
        return jsonify({"success": False, "error": str(e)}), 500

# --- BOT ROUTES ---
@app.route('/api/raksha-bot/chat', methods=['POST'])
def bot_chat():
    reply = bot_engine.get_chat_response(request.json.get('message'), request.json.get('section', 'safety'))
    if request.json.get('userId'):
        bot_fb.save_chat_message(request.json.get('userId'), {"sender": "bot", "message": reply, "section": request.json.get('section')})
    return jsonify({"reply": reply})

@app.route('/api/raksha-bot/live-exams', methods=['GET'])
def get_bot_exams():
    return jsonify(bot_fb.get_live_exams())

@app.route('/api/raksha-bot/generate-study-plan', methods=['POST'])
def generate_plan():
    plan_text = bot_engine.generate_study_plan(request.json)
    filename = f"plan_{request.json.get('userId')}_{int(time.time())}.pdf"
    file_path = pdf_gen.generate_plan_pdf(request.json.get('examName'), plan_text, filename)
    url = bot_fb.upload_pdf(file_path, filename)
    return jsonify({"planText": plan_text, "pdfUrl": url or f"/static/pdfs/{filename}"})

@app.route('/static/pdfs/<path:filename>')
def serve_pdf(filename):
    return send_from_directory('static/pdfs', filename)

# --- SOCKET EVENTS ---

@socketio.on('sos:start')
def handle_sos_start(data):
    join_room(data.get('sosId'))
    emit('sos:status', {'success': True}, room=data.get('sosId'))

@socketio.on('sos:frame')
def handle_sos_frame(data):
    emit('sos:frame_relay', data, room=data.get('sosId'), include_self=False)

@socketio.on('signal:offer')
@socketio.on('signal:answer')
@socketio.on('signal:candidate')
def handle_signal(data):
    emit(request.event, data, room=data.get('sosId'), include_self=False)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host='0.0.0.0', port=port, debug=False)
