import firebase_admin
from firebase_admin import credentials, firestore, storage
import os
from datetime import datetime
import dateutil.parser

class RakshaFirebaseService:
    def __init__(self):
        self.db = firestore.client()
        try:
            self.bucket = storage.bucket()
        except:
            self.bucket = None

    def get_live_exams(self):
        """
        Fetches MANUALLY UPLOADED exam notices.
        Automatically expires notices if today > applicationLastDate.
        """
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
                        # Attempt to parse common formats: DD-MM-YYYY or YYYY-MM-DD
                        last_date = dateutil.parser.parse(last_date_str, dayfirst=True)
                        if last_date < now:
                            # Logically expired, skip or mark for deletion
                            print(f"[Auto-Expiry] Skipping expired exam: {data.get('title')}")
                            continue
                    except:
                        pass # If date format is un-parsable, we keep it for safety
                
                live_list.append({**data, 'id': doc.id})
                
            return live_list
        except Exception as e:
            print(f"[Bot Firebase] Error fetching manual exams: {e}")
            return []

    def get_latest_notices(self, types=None):
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

    # ... rest of the service ...
