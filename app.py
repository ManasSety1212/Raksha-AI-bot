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

db = firestore.client()
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

# --- BOT ROUTES ---

@app.route('/api/raksha-bot/chat', methods=['POST'])
def bot_chat():
    data = request.json
    reply = bot_engine.get_chat_response(data.get('message'), data.get('section', 'safety'))
    if data.get('userId'):
        bot_fb.save_chat_message(data.get('userId'), {"sender": "bot", "message": reply, "section": data.get('section')})
    return jsonify({"reply": reply})

@app.route('/api/raksha-bot/live-exams', methods=['GET'])
def get_bot_exams():
    return jsonify(bot_fb.get_live_exams())

@app.route('/api/raksha-bot/generate-study-plan', methods=['POST'])
def generate_plan():
    data = request.json
    plan_text = bot_engine.generate_study_plan(data)
    filename = f"plan_{data.get('userId')}_{int(time.time())}.pdf"
    file_path = pdf_gen.generate_plan_pdf(data.get('examName'), plan_text, filename)
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
