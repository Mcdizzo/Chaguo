-- SQLite schema for Tanzania university admissions predictor.
-- This file defines universities, programs, and cutoffs with foreign key relationships.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS universities (
    uni_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    head_office TEXT,
    type TEXT,
    status TEXT,
    university_institution_id INTEGER UNIQUE,
    website TEXT
);

CREATE TABLE IF NOT EXISTS programs (
    program_id INTEGER PRIMARY KEY AUTOINCREMENT,
    uni_id INTEGER NOT NULL,
    program_name TEXT NOT NULL,
    program_code TEXT,
    award_level TEXT,
    duration_years REAL,
    minimum_points REAL,
    admission_capacity INTEGER,
    requirements_raw TEXT,
    FOREIGN KEY (uni_id)
        REFERENCES universities (uni_id)
        ON UPDATE CASCADE
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS cutoffs (
    cutoff_id INTEGER PRIMARY KEY AUTOINCREMENT,
    program_id INTEGER NOT NULL,
    year INTEGER NOT NULL,
    minimum_points REAL,
    subject_combination TEXT,
    FOREIGN KEY (program_id)
        REFERENCES programs (program_id)
        ON UPDATE CASCADE
        ON DELETE CASCADE
);
