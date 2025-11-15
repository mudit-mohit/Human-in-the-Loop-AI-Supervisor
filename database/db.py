import sqlite3
import json
import uuid
from datetime import datetime
from contextlib import contextmanager
import logging
import difflib
import re

logger = logging.getLogger(__name__)

class Database:
    def __init__(self, db_path="salon_ai.db"):
        self.db_path = db_path
        self._init_db()
    
    @contextmanager
    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()
    
    def _init_db(self):
        with self._get_connection() as conn:
            # Customers
            conn.execute('''
                CREATE TABLE IF NOT EXISTS customers (
                    id TEXT PRIMARY KEY,
                    phone_number TEXT UNIQUE NOT NULL,
                    name TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Help requests with phone_number
            conn.execute('''
                CREATE TABLE IF NOT EXISTS help_requests (
                    id TEXT PRIMARY KEY,
                    question TEXT NOT NULL,
                    caller_id TEXT NOT NULL,
                    phone_number TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    supervisor_answer TEXT,
                    context TEXT
                )
            ''')
            
            # Knowledge base
            conn.execute('''
                CREATE TABLE IF NOT EXISTS knowledge_base (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    question TEXT NOT NULL,
                    answer TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            self._seed_initial_data(conn)
    
    def _seed_initial_data(self, conn):
        initial_data = [
            ("what are your hours", "We're open Monday to Friday 9AM-7PM, Saturday 10AM-5PM"),
            ("when are you open", "Our hours are Monday-Friday 9AM-7PM, Saturday 10AM-5PM"),
            ("where are you located", "We're at 123 Beauty Street, Glamour City"),
            ("what services do you offer", "We offer haircuts, coloring, styling, and spa treatments"),
            ("how much is a haircut", "Haircuts start at $45"),
            ("do you accept walk ins", "Yes, we accept walk-ins based on availability"),
            ("do you take walk ins", "Yes, we accept walk-ins based on availability"),
            ("walk ins", "Yes, we accept walk-ins based on stylist availability"),
            ("how to book appointment", "You can book by calling us or through our website"),
            ("what is your cancellation policy", "We require 24 hours notice for cancellations"),
            ("do you offer hair coloring", "Yes, we offer professional hair coloring services"),
            ("what brands do you use", "We use premium brands like Redken and Olaplex")
        ]
    
        for question, answer in initial_data:
            conn.execute(
                "INSERT OR IGNORE INTO knowledge_base (question, answer) VALUES (?, ?)",
                (question.lower(), answer)
            )
    
    def get_answer(self, question):
        q = question.lower().strip()
        q = re.sub(r'[^\w\s]', '', q)
        q = re.sub(r'\s+', ' ', q)

        with self._get_connection() as conn:
            rows = conn.execute('SELECT question, answer FROM knowledge_base').fetchall()
            kb = [(re.sub(r'[^\w\s]', '', r['question'].lower()), r['answer']) for r in rows]

        # 1. Exact normalized
        for k, a in kb:
            if k == q:
                return a
        # 2. Substring
        for k, a in kb:
            if k in q or q in k:
                return a
        # 3. Fuzzy
        for k, a in kb:
            if difflib.SequenceMatcher(None, q, k).ratio() > 0.8:
                return a
        # 4. Keyword overlap
        q_words = set(q.split())
        for k, a in kb:
            if len(q_words & set(k.split())) >= 2:
                return a
        return None
    
    def add_knowledge(self, question, answer):
        with self._get_connection() as conn:
            conn.execute(
                "INSERT INTO knowledge_base (question, answer) VALUES (?, ?)",
                (question.lower(), answer)
            )
    
    def create_help_request(self, question, caller_id, phone_number=None):
        request_id = str(uuid.uuid4())
        with self._get_connection() as conn:
            conn.execute(
                "INSERT INTO help_requests (id, question, caller_id, phone_number) VALUES (?, ?, ?, ?)",
                (request_id, question, caller_id, phone_number)
            )
        logger.info(f"✅ Help request created: {request_id} for {phone_number}")
        return request_id
    
    def get_pending_requests(self):
        with self._get_connection() as conn:
            # Get only truly pending requests
            results = conn.execute('''
                SELECT hr.*, c.phone_number as customer_phone
                FROM help_requests hr 
                LEFT JOIN customers c ON hr.caller_id = c.id 
                WHERE hr.status = 'pending'
                ORDER BY hr.created_at DESC
            ''').fetchall()
            
            # Convert to dict and ensure phone_number is set
            requests = []
            for row in results:
                req = dict(row)
                # Use hr.phone_number if available, otherwise customer_phone
                if not req.get('phone_number'):
                    req['phone_number'] = req.get('customer_phone', 'Unknown')
                requests.append(req)
            
            return requests
    
    def resolve_request(self, request_id, answer):
        with self._get_connection() as conn:
            conn.execute(
                "UPDATE help_requests SET status = 'resolved', supervisor_answer = ? WHERE id = ?",
                (answer, request_id)
            )
        logger.info(f"✅ Request {request_id} resolved")
    
    def get_or_create_customer(self, phone_number, name=None):
        with self._get_connection() as conn:
            customer = conn.execute(
                "SELECT * FROM customers WHERE phone_number = ?", 
                (phone_number,)
            ).fetchone()
            if customer:
                return dict(customer)
            customer_id = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO customers (id, phone_number, name) VALUES (?, ?, ?)",
                (customer_id, phone_number, name or "Unknown")
            )
            return dict(conn.execute("SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone())
    
    def get_knowledge_base(self):
        with self._get_connection() as conn:
            results = conn.execute('SELECT question, answer FROM knowledge_base').fetchall()
            return {row['question']: row['answer'] for row in results}
    
    def get_all_requests(self):
        with self._get_connection() as conn:
            results = conn.execute('''
                SELECT hr.*, c.phone_number as customer_phone
                FROM help_requests hr 
                LEFT JOIN customers c ON hr.caller_id = c.id 
                ORDER BY hr.created_at DESC
            ''').fetchall()
            
            # Convert to dict and ensure phone_number is set
            requests = []
            for row in results:
                req = dict(row)
                # Use hr.phone_number if available, otherwise customer_phone
                if not req.get('phone_number'):
                    req['phone_number'] = req.get('customer_phone', 'Unknown')
                requests.append(req)
            
            logger.info(f"📊 Retrieved {len(requests)} total requests")
            for req in requests:
                logger.info(f"  - {req['id'][:8]}... | Status: {req['status']} | Phone: {req.get('phone_number', 'N/A')}")
            
            return requests