PRAGMA application_id=1465406036;
PRAGMA user_version=1;
CREATE TABLE channel (id INTEGER PRIMARY KEY CHECK(id=1),bot TEXT NOT NULL,
                    owner TEXT NOT NULL,cursor TEXT NOT NULL DEFAULT '');
CREATE TABLE inbox (message_id TEXT PRIMARY KEY,text TEXT NOT NULL,context TEXT,
                    created_ms INTEGER NOT NULL,seq INTEGER NOT NULL,received_at REAL NOT NULL,
                    phase TEXT NOT NULL,conflict INTEGER NOT NULL DEFAULT 0);
CREATE TABLE outbox (id TEXT PRIMARY KEY,text TEXT NOT NULL,priority INTEGER NOT NULL,
                    state TEXT NOT NULL,context TEXT,server_id TEXT,task_id TEXT,kind TEXT NOT NULL,
                    created_at REAL NOT NULL);
CREATE TABLE reply_context (id INTEGER PRIMARY KEY CHECK(id=1),token TEXT NOT NULL,
                    created_ms INTEGER NOT NULL,seq INTEGER NOT NULL);
CREATE TABLE tasks (id TEXT PRIMARY KEY,source_message_id TEXT UNIQUE,client_id TEXT UNIQUE,
                    target TEXT NOT NULL,thread_id TEXT NOT NULL,input TEXT NOT NULL,state TEXT NOT NULL,
                    queue_id TEXT,turn_id TEXT,created_at REAL NOT NULL,updated_at REAL NOT NULL);
