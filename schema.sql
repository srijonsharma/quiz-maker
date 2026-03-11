CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    mobile TEXT NOT NULL,
    institution TEXT NOT NULL,
    password TEXT NOT NULL,
    is_admin INTEGER DEFAULT 0 -- 1 for admin, 0 for regular user
);

CREATE TABLE IF NOT EXISTS quizzes (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    creator_id INTEGER,
    is_public INTEGER DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (creator_id) REFERENCES users (id)
);

CREATE TABLE IF NOT EXISTS questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    quiz_id TEXT,
    question_text TEXT NOT NULL,
    option_a TEXT NOT NULL,
    option_b TEXT NOT NULL,
    option_c TEXT NOT NULL,
    option_d TEXT NOT NULL,
    correct_option TEXT NOT NULL,
    FOREIGN KEY (quiz_id) REFERENCES quizzes (id)
);

CREATE TABLE IF NOT EXISTS quiz_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    quiz_id TEXT,
    user_id INTEGER,
    participant_name TEXT,
    participant_email TEXT,
    participant_mobile TEXT,
    participant_institution TEXT,
    score INTEGER,
    total INTEGER,
    attempt_date DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (quiz_id) REFERENCES quizzes (id),
    FOREIGN KEY (user_id) REFERENCES users (id)
);
