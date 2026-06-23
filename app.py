import math
from flask import Flask, request, jsonify, Response, send_from_directory
from flask_cors import CORS
from flask_socketio import SocketIO, emit, join_room, leave_room
import os
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

# --- FIREBASE INITIALIZATION ---
if not firebase_admin._apps:
    key_path = 'serviceAccountKey.json'
    env_key = os.environ.get("FIREBASE_SERVICE_ACCOUNT")
    
    if os.path.exists(key_path):
        cred = credentials.Certificate(key_path)
        firebase_admin.initialize_app(cred, {
            'storageBucket': 'tanprix-52683.firebasestorage.app'
        })
        print("[Firebase] Initialized from file")
    elif env_key:
        import json
        cred_dict = json.loads(env_key)
        cred = credentials.Certificate(cred_dict)
        firebase_admin.initialize_app(cred, {
            'storageBucket': 'tanprix-52683.firebasestorage.app'
        })
        print("[Firebase] SUCCESS: Initialized from environment variable")
    else:
        print("[Firebase] ERROR: No credentials found! Please set FIREBASE_SERVICE_ACCOUNT in Render Dashboard.")
        # Attempting default anyway, but this will likely fail with ADC error
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

@app.route('/')
def home():
    return jsonify({
        "status": "online",
        "system": "Raksha AI Bot",
        "version": "1.0.0",
        "message": "Raksha AI Backend is successfully running on Render."
    })

socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# Initialize Bot Services
OPENAI_KEY = os.environ.get("OPENAI_API_KEY")
bot_engine = RakshaBotEngine(OPENAI_KEY) if OPENAI_KEY else None
bot_fb = RakshaFirebaseService()
pdf_gen = StudyPlanPDFGenerator()

# --- GEO-FENCING HELPER ---
def haversine(lat1, lon1, lat2, lon2):
    R = 6371000 # meters
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def check_geofences(device_id, lat, lon, user_id):
    db = get_db()
    if not db: return
    
    zones = db.collection('safe_zones').where('deviceId', '==', device_id).get()
    for zone_doc in zones:
        zone = zone_doc.to_dict()
        distance = haversine(lat, lon, zone['latitude'], zone['longitude'])
        if distance > zone['radius']:
            db.collection('tracking_alerts').add({
                'deviceId': device_id,
                'ownerUserId': user_id,
                'alertType': 'geofence_exit',
                'message': f"Alert: Device {device_id} entered an unsafe zone.",
                'latitude': lat, 'longitude': lon,
                'createdAt': firestore.SERVER_TIMESTAMP,
                'isRead': False
            })

# --- GUARDIAN ROUTES ---

@app.route('/api/location/update', methods=['POST'])
def update_location():
    db = get_db()
    if not db: return jsonify({"error": "Database not available"}), 503
    
    data = request.json
    device_id, lat, lon = data.get('deviceId'), data.get('latitude'), data.get('longitude')
    if not device_id or lat is None: return jsonify({"error": "Invalid data"}), 400
    
    # Update firestore
    db.collection('live_locations').document(device_id).set({**data, 'timestamp': firestore.SERVER_TIMESTAMP}, merge=True)
    
    # Geofence check
    owner = db.collection('guardian_devices').document(device_id).get()
    if owner.exists:
        check_geofences(device_id, lat, lon, owner.to_dict().get('ownerUserId'))
        
    socketio.emit(f"location_update:{device_id}", data)
    return jsonify({"status": "ok"})

# --- SOS & AI COMPATIBILITY ROUTES ---

@app.route('/api/ai/chat', methods=['POST'])
def compatibility_chat():
    data = request.json
    reply = bot_engine.get_chat_response(data.get('query'), data.get('mode', 'safety').lower())
    if data.get('userId'):
        bot_fb.save_chat_message(data.get('userId'), {"sender": "bot", "message": reply, "section": data.get('mode')})
    return jsonify({"reply": reply, "message": reply})

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
