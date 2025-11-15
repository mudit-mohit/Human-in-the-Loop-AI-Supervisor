# migrate_db.py
from database.db import Database

db = Database()
with db._get_connection() as conn:
    conn.execute("PRAGMA foreign_keys=off")
    conn.execute("BEGIN TRANSACTION")
    
    # Create new table
    conn.execute('''
        CREATE TABLE help_requests_new (
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
    
    # Copy data
    conn.execute('''
        INSERT INTO help_requests_new 
        SELECT id, question, caller_id, NULL, status, created_at, supervisor_answer, context 
        FROM help_requests
    ''')
    
    # Replace
    conn.execute("DROP TABLE help_requests")
    conn.execute("ALTER TABLE help_requests_new RENAME TO help_requests")
    
    conn.execute("PRAGMA foreign_keys=on")
    print("DB migrated!")