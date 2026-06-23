import firebase_admin
from firebase_admin import credentials, firestore, storage
import os
from datetime import datetime
import dateutil.parser

class RakshaFirebaseService:
    def __init__(self):
        self._db = None
        self._bucket = None

    @property
    def db(self):
        if self._db is None:
            try:
                self._db = firestore.client()
            except Exception:
                print("[Firebase Service] DB Access Failed")
        return self._db

    @property
    def bucket(self):
        if self._bucket is None:
            try:
                self._bucket = storage.bucket()
            except Exception:
                print("[Firebase Service] Storage Access Failed")
        return self._bucket

    def save_chat_message(self, user_id, message_dict):
        """
        Saves a chat message to the user's history.
        """
        if not self.db: return False
        try:
            self.db.collection('users').document(user_id).collection('bot_chats').add({
                **message_dict,
                'createdAt': firestore.SERVER_TIMESTAMP
            })
            return True
        except Exception as e:
            print(f"[Firebase] Error saving chat: {e}")
            return False

    def upload_pdf(self, file_path, filename):
        """
        Uploads a generated study plan PDF to Firebase Storage.
        """
        if not self.bucket: return None
        try:
            blob = self.bucket.blob(f"study_plans/{filename}")
            blob.upload_from_filename(file_path)
            blob.make_public()
            return blob.public_url
        except Exception as e:
            print(f"[Firebase] Error uploading PDF: {e}")
            return None

    def get_live_exams(self):
        """
        Fetches MANUALLY UPLOADED exam notices.
        """
        if not self.db: return []
        try:
            now = datetime.now()
            docs = self.db.collection('manual_updates') \
                .where('status', '==', 'published') \
                .where('updateType', '==', 'exam') \
                .where('isApplicationLive', '==', True) \
                .get()
                
            live_list = []
            for doc in docs:
                data = doc.to_dict()
                last_date_str = data.get('applicationLastDate')
                
                # Auto-Expiry Logic
                if last_date_str:
                    try:
                        last_date = dateutil.parser.parse(last_date_str, dayfirst=True)
                        if last_date < now:
                            continue
                    except:
                        pass
                
                live_list.append({**data, 'id': doc.id})
            return live_list
        except Exception as e:
            print(f"[Bot Firebase] Error fetching manual exams: {e}")
            return []

    def get_latest_notices(self, types=None):
        if not self.db: return []
        try:
            now = datetime.now()
            query = self.db.collection('manual_updates').where('status', '==', 'published')
            if types:
                query = query.where('updateType', 'in', types)
            
            docs = query.order_by('createdAt', direction=firestore.Query.DESCENDING).limit(20).get()
            
            filtered = []
            for doc in docs:
                data = doc.to_dict()
                last_date_str = data.get('applicationLastDate')
                if last_date_str:
                    try:
                        if dateutil.parser.parse(last_date_str, dayfirst=True) < now:
                            continue
                    except: pass
                filtered.append({**data, 'id': doc.id})
            return filtered[:10]
        except Exception as e:
            print(f"[Bot Firebase] Error fetching notices: {e}")
            return []
