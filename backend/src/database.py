import sqlite3
import os
import logging

logger = logging.getLogger("fraud-db")

# Database File Path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(SCRIPT_DIR, "fraud.db")

class FraudDB:
    def __init__(self):
        self.conn = sqlite3.connect(DB_FILE, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row # Access columns by name
        self._init_table()

    def _init_table(self):
        """Create the table and seed data if it doesn't exist."""
        cursor = self.conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS fraud_cases (
                customer_id TEXT PRIMARY KEY,
                name TEXT,
                phone TEXT,
                security_question TEXT,
                security_answer TEXT,
                card_last4 TEXT,
                merchant TEXT,
                amount TEXT,
                location TEXT,
                timestamp TEXT,
                status TEXT,
                notes TEXT
            )
        ''')
        self.conn.commit()
        
        # Seed data if empty
        cursor.execute('SELECT count(*) FROM fraud_cases')
        if cursor.fetchone()[0] == 0:
            logger.info("Seeding database with mock data...")
            self.add_mock_case({
                "customer_id": "CUST_9988",
                "name": "John Doe",
                "phone": "+15550199",
                "security_question": "What is the name of your first pet?",
                "security_answer": "Max",
                "card_last4": "8842",
                "merchant": "Apple Store",
                "amount": "$1,299.00",
                "location": "New York, NY",
                "timestamp": "Yesterday at 4:30 PM",
                "status": "pending_review",
                "notes": "Suspicious login detected."
            })

    def add_mock_case(self, data):
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT INTO fraud_cases VALUES 
            (:customer_id, :name, :phone, :security_question, :security_answer, 
             :card_last4, :merchant, :amount, :location, :timestamp, :status, :notes)
        ''', data)
        self.conn.commit()

    def get_case_by_phone(self, phone_identity: str):
        """Find case where stored phone is inside the caller ID."""
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM fraud_cases')
        cases = cursor.fetchall()
        
        for case in cases:
            # Simple check if the db phone number is part of the SIP caller ID
            if case["phone"] and case["phone"] in phone_identity:
                return dict(case)
        return None

    def get_case_by_name(self, name: str):
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM fraud_cases WHERE lower(name) = ?', (name.lower(),))
        row = cursor.fetchone()
        return dict(row) if row else None

    def update_case_status(self, customer_id: str, status: str, note: str):
        cursor = self.conn.cursor()
        # Fetch existing notes to append
        cursor.execute('SELECT notes FROM fraud_cases WHERE customer_id = ?', (customer_id,))
        current_note = cursor.fetchone()['notes']
        new_note = f"{current_note} | [Agent]: {note}"
        
        cursor.execute('''
            UPDATE fraud_cases 
            SET status = ?, notes = ?
            WHERE customer_id = ?
        ''', (status, new_note, customer_id))
        self.conn.commit()
        return True

    def close(self):
        self.conn.close()