ALTER TABLE users ADD COLUMN accent_color TEXT NOT NULL DEFAULT 'green';
ALTER TABLE users ADD COLUMN market_country TEXT NOT NULL DEFAULT 'IN';
ALTER TABLE users ADD COLUMN meta_ai_enabled INTEGER NOT NULL DEFAULT 0;

CREATE TABLE career_insights (
    career_id TEXT NOT NULL,
    country_code TEXT NOT NULL,
    report TEXT NOT NULL,
    sources_json TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (career_id, country_code)
);
