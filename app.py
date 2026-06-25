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

@app.route("/", methods=["GET"])
def index():
    return jsonify({
        "message": "Raksha AI Bot backend running",
        "status": "ok",
        "version": "1.0.2"
    })

@app.route("/api/debug/env", methods=["GET"])
def debug_env():
    return jsonify({
        "status": "ok",
        "openai_key_present": bool(os.getenv("OPENAI_API_KEY")),
        "google_key_present": bool(os.getenv("GOOGLE_MAPS_API_KEY")),
        "firebase_key_present": bool(os.getenv("FIREBASE_SERVICE_ACCOUNT"))
    })

@app.route("/api/routes", methods=["GET"])
def list_routes():
    import urllib.parse
    output = []
    for rule in app.url_map.iter_rules():
        methods = ','.join(rule.methods)
        url = urllib.parse.unquote(str(rule))
        output.append({"route": url, "methods": methods})
    return jsonify({
        "success": True,
        "routes": output
    })

@app.route('/api/location/update', methods=['POST'])
def location_update():
    # Placeholder for geofencing logic
    data = request.get_json(silent=True) or {}
    print(f"[Geofence] Update from {data.get('deviceId')}: {data.get('latitude')}, {data.get('longitude')}")
    return jsonify({"success": True, "status": "Location synchronized"})

@app.route('/api/auth/register', methods=['POST'])
def register_face():
    return jsonify({"success": True, "message": "Registered"})

# --- NEARBY POLICE STATION DETECTION ---

@app.route('/api/nearby/police', methods=['GET'])
def get_nearby_police():
    try:
        lat = float(request.args.get('lat'))
        lng = float(request.args.get('lng'))
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "Invalid coordinates"}), 400

    api_key = os.environ.get("GOOGLE_MAPS_API_KEY")
    places = []
    debug = {"queries": []}
    
    def calculate_distance(lat1, lon1, lat2, lon2):
        R = 6371  # Earth radius in KM
        dLat = math.radians(lat2 - lat1)
        dLon = math.radians(lon2 - lon1)
        a = math.sin(dLat / 2) * math.sin(dLat / 2) + \
            math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * \
            math.sin(dLon / 2) * math.sin(dLon / 2)
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return R * c

    if not api_key or api_key == "placeholder_change_in_render_dashboard":
        return jsonify({"success": False, "error": "Google Maps API Key is missing on server"}), 500

    try:
        import requests
        
        # SEARCH STRATEGY: Try multiple queries to catch regional terms (Thana, Chowki)
        queries = [
            f"police station near {lat},{lng}",
            f"thana near {lat},{lng}",
            f"police chowki near {lat},{lng}"
        ]
        
        seen_place_ids = set()
        
        for q in queries:
            if len(places) >= 10: break
            
            text_url = "https://maps.googleapis.com/maps/api/place/textsearch/json"
            params = {
                "query": q,
                "location": f"{lat},{lng}",
                "radius": 30000,
                "key": api_key
            }
            resp = requests.get(text_url, params=params, timeout=10)
            data = resp.json()
            
            debug["queries"].append({
                "query": q,
                "status": data.get('status'),
                "count": len(data.get('results', [])),
                "error": data.get('error_message')
            })

            if data.get('status') == 'OK':
                for item in data.get('results', []):
                    place_id = item.get('place_id')
                    if place_id not in seen_place_ids:
                        seen_place_ids.add(place_id)
                        p_lat = item.get('geometry', {}).get('location', {}).get('lat')
                        p_lng = item.get('geometry', {}).get('location', {}).get('lng')
                        dist = calculate_distance(lat, lng, p_lat, p_lng)
                        
                        places.append({
                            "name": item.get('name'),
                            "address": item.get('formatted_address') or item.get('vicinity'),
                            "latitude": p_lat,
                            "longitude": p_lng,
                            "distanceKm": round(dist, 2),
                            "rating": item.get('rating'),
                            "openNow": item.get('opening_hours', {}).get('open_now'),
                            "placeId": place_id,
                            "mapsUrl": f"https://www.google.com/maps/search/?api=1&query={p_lat},{p_lng}&query_place_id={place_id}"
                        })
            
            # Stop if we found enough from the first query to keep it fast
            if len(places) > 5: break

        # SORT BY DISTANCE
        places.sort(key=lambda x: x['distanceKm'])
        final_places = places[:10]

        return jsonify({
            "success": True,
            "places": final_places,
            "count": len(final_places),
            "debug": debug,
            "message": "Results found" if final_places else "No police stations found. Try searching in Google Maps app."
        })

    except Exception as e:
        app.logger.exception("Nearby API Broad Search Failure")
        return jsonify({"success": False, "error": str(e)}), 500

# --- BOT ROUTES ---
@app.route('/api/ai/chat', methods=['POST'])
def bot_chat():
    data = request.get_json(silent=True) or {}
    msg = data.get('message')
    section = data.get('section', 'safety')
    
    if not msg:
        return jsonify({"reply": "I didn't receive any message."}), 400
        
    reply = bot_engine.get_chat_response(msg, section)
    if data.get('userId'):
        bot_fb.save_chat_message(data.get('userId'), {"sender": "bot", "message": reply, "section": section})
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
