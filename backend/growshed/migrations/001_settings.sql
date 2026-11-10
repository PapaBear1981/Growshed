-- User preferences shared by every screen (e.g. display_units = imperial | metric).
CREATE TABLE setting (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
