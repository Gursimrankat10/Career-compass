CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
    display_name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    theme TEXT NOT NULL DEFAULT 'dark' CHECK (theme IN ('dark', 'light')),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_progress (
    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    xp INTEGER NOT NULL DEFAULT 0,
    streak INTEGER NOT NULL DEFAULT 0,
    last_active TEXT,
    selected_career TEXT
);

CREATE TABLE IF NOT EXISTS assessments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    scores TEXT NOT NULL,
    answered_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS assessments_user_created
    ON assessments(user_id, created_at);

CREATE TABLE IF NOT EXISTS task_completions (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    task_id TEXT NOT NULL,
    completed_on TEXT NOT NULL,
    PRIMARY KEY (user_id, task_id, completed_on)
);

CREATE TABLE IF NOT EXISTS daily_task_plans (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    plan_date TEXT NOT NULL,
    task_ids TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (user_id, plan_date)
);

CREATE TABLE IF NOT EXISTS mentor_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user', 'mentor')),
    message TEXT NOT NULL,
    sources TEXT NOT NULL DEFAULT '[]',
    intent TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS mentor_messages_user_id
    ON mentor_messages(user_id, id);

CREATE TABLE IF NOT EXISTS learning_tests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    career_id TEXT,
    level INTEGER NOT NULL,
    questions_json TEXT NOT NULL,
    answers_json TEXT NOT NULL DEFAULT '{}',
    score INTEGER,
    correct_count INTEGER,
    total_count INTEGER NOT NULL,
    started_at TEXT NOT NULL,
    submitted_at TEXT,
    timed_out INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS learning_tests_user_submitted
    ON learning_tests(user_id, submitted_at);

CREATE TABLE IF NOT EXISTS career_feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    career_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    performance_json TEXT NOT NULL,
    recommendations_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
