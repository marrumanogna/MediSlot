
-- =========================================================
-- MEDISLOT DATABASE SCHEMA
-- MySQL
-- =========================================================

CREATE DATABASE IF NOT EXISTS medislot;
USE medislot;


-- =========================================================
-- 1. USERS TABLE
-- Stores login and account information for doctors/patients
-- =========================================================

CREATE TABLE IF NOT EXISTS users (
    user_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    first_name VARCHAR(100) NULL,
    last_name VARCHAR(100) NULL,
    email VARCHAR(254) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    role ENUM('PATIENT', 'DOCTOR') NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,

    INDEX idx_users_role_active (role, is_active)
);


-- =========================================================
-- 2. DOCTOR PROFILES TABLE
-- Stores professional information of doctors
-- =========================================================

CREATE TABLE IF NOT EXISTS doctor_profiles (
    user_id BIGINT UNSIGNED PRIMARY KEY,
    full_name VARCHAR(201) NOT NULL,
    licence_number VARCHAR(100) NOT NULL,
    specialization VARCHAR(120) NOT NULL,
    qualifications JSON NOT NULL,
    experience_years SMALLINT UNSIGNED NOT NULL DEFAULT 0,
    hospital_name VARCHAR(200) NOT NULL,
    hospital_address VARCHAR(500) NOT NULL,
    languages_spoken JSON NOT NULL,
    bio TEXT NULL,
    consultation_fee DECIMAL(10,2) NULL,
    photo_key VARCHAR(1024) NULL,
    timezone VARCHAR(64) NOT NULL DEFAULT 'UTC',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,

    UNIQUE KEY uq_doctor_licence_number (licence_number),

    CONSTRAINT fk_doctor_user
        FOREIGN KEY (user_id)
        REFERENCES users(user_id)
        ON DELETE CASCADE,

    CONSTRAINT chk_doctor_experience
        CHECK (experience_years <= 80),

    CONSTRAINT chk_doctor_fee
        CHECK (consultation_fee IS NULL OR consultation_fee >= 0)
);


-- =========================================================
-- 3. PATIENTS TABLE
-- Stores patient profile information
-- =========================================================

CREATE TABLE IF NOT EXISTS patients (
    patient_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT UNSIGNED NOT NULL UNIQUE,
    full_name VARCHAR(150) NOT NULL,
    date_of_birth DATE NULL,
    gender VARCHAR(20) NULL,
    phone VARCHAR(20) NULL,
    address TEXT NULL,
    city VARCHAR(100) NULL,
    emergency_contact VARCHAR(20) NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,

    CONSTRAINT fk_patient_user
        FOREIGN KEY (user_id)
        REFERENCES users(user_id)
        ON DELETE CASCADE
);


-- =========================================================
-- 4. CONSULTATION TYPES TABLE
-- Stores consultation services offered by doctors
-- =========================================================

CREATE TABLE IF NOT EXISTS consultation_types (
    consultation_type_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    doctor_id BIGINT UNSIGNED NOT NULL,
    name VARCHAR(120) NOT NULL,
    description VARCHAR(500) NULL,
    duration_minutes SMALLINT UNSIGNED NOT NULL DEFAULT 30,
    fee DECIMAL(10,2) NOT NULL DEFAULT 0.00,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,

    UNIQUE KEY uq_doctor_consultation_name (doctor_id, name),

    CONSTRAINT fk_consultation_doctor
        FOREIGN KEY (doctor_id)
        REFERENCES doctor_profiles(user_id)
        ON DELETE CASCADE,

    CONSTRAINT chk_consultation_duration
        CHECK (duration_minutes BETWEEN 5 AND 480),

    CONSTRAINT chk_consultation_fee
        CHECK (fee >= 0)
);


-- =========================================================
-- 5. AVAILABILITY PATTERNS TABLE
-- Stores doctors' regular weekly availability
-- =========================================================

CREATE TABLE IF NOT EXISTS availability_patterns (
    pattern_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    doctor_id BIGINT UNSIGNED NOT NULL,
    day_of_week TINYINT UNSIGNED NOT NULL,
    start_time TIME NOT NULL,
    end_time TIME NOT NULL,
    timezone VARCHAR(64) NOT NULL DEFAULT 'UTC',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,

    INDEX idx_availability_doctor_day
        (doctor_id, day_of_week, is_active),

    CONSTRAINT fk_availability_doctor
        FOREIGN KEY (doctor_id)
        REFERENCES doctor_profiles(user_id)
        ON DELETE CASCADE,

    CONSTRAINT chk_availability_day
        CHECK (day_of_week BETWEEN 0 AND 6),

    CONSTRAINT chk_availability_time
        CHECK (start_time < end_time)
);


-- =========================================================
-- 6. DOCTOR BLACKOUT DATES TABLE
-- Stores dates when doctors are unavailable
-- =========================================================

CREATE TABLE IF NOT EXISTS doctor_blackout_dates (
    blackout_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    doctor_id BIGINT UNSIGNED NOT NULL,
    blackout_date DATE NOT NULL,
    reason VARCHAR(255) NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE KEY uq_doctor_blackout_date
        (doctor_id, blackout_date),

    CONSTRAINT fk_blackout_doctor
        FOREIGN KEY (doctor_id)
        REFERENCES doctor_profiles(user_id)
        ON DELETE CASCADE
);


-- =========================================================
-- 7. APPOINTMENT SLOTS TABLE
-- Stores generated appointment slots
-- =========================================================

CREATE TABLE IF NOT EXISTS appointment_slots (
    slot_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    doctor_id BIGINT UNSIGNED NOT NULL,
    consultation_type_id BIGINT UNSIGNED NOT NULL,
    slot_start DATETIME NOT NULL,
    slot_end DATETIME NOT NULL,
    status ENUM('AVAILABLE', 'BOOKED', 'BLOCKED')
        NOT NULL DEFAULT 'AVAILABLE',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE KEY uq_doctor_consultation_slot
        (doctor_id, consultation_type_id, slot_start),

    INDEX idx_doctor_slot_status
        (doctor_id, status, slot_start),

    CONSTRAINT fk_slot_doctor
        FOREIGN KEY (doctor_id)
        REFERENCES doctor_profiles(user_id)
        ON DELETE CASCADE,

    CONSTRAINT fk_slot_consultation
        FOREIGN KEY (consultation_type_id)
        REFERENCES consultation_types(consultation_type_id)
        ON DELETE CASCADE,

    CONSTRAINT chk_slot_time
        CHECK (slot_start < slot_end)
);


-- =========================================================
-- DROPDOWN OPTION TABLES
-- These tables provide default registration form options
-- =========================================================


-- =========================================================
-- 8. SPECIALISATION OPTIONS
-- =========================================================

CREATE TABLE IF NOT EXISTS specialization_options (
    specialization VARCHAR(120) PRIMARY KEY,
    sort_order INT NOT NULL
);

INSERT IGNORE INTO specialization_options
    (specialization, sort_order)
VALUES
    ('General Medicine', 1),
    ('Cardiology', 2),
    ('Dermatology', 3),
    ('Dentistry', 4),
    ('ENT', 5),
    ('Gynaecology', 6),
    ('Neurology', 7),
    ('Orthopaedics', 8),
    ('Paediatrics', 9),
    ('Psychiatry', 10);


-- =========================================================
-- 9. EXPERIENCE OPTIONS
-- Values from 0 to 80 years
-- =========================================================

CREATE TABLE IF NOT EXISTS experience_options (
    experience_years TINYINT UNSIGNED PRIMARY KEY
);

INSERT IGNORE INTO experience_options (experience_years)
VALUES
    (0),(1),(2),(3),(4),(5),(6),(7),(8),(9),
    (10),(11),(12),(13),(14),(15),(16),(17),(18),(19),
    (20),(21),(22),(23),(24),(25),(26),(27),(28),(29),
    (30),(31),(32),(33),(34),(35),(36),(37),(38),(39),
    (40),(41),(42),(43),(44),(45),(46),(47),(48),(49),
    (50),(51),(52),(53),(54),(55),(56),(57),(58),(59),
    (60),(61),(62),(63),(64),(65),(66),(67),(68),(69),
    (70),(71),(72),(73),(74),(75),(76),(77),(78),(79),(80);


-- =========================================================
-- 10. QUALIFICATION OPTIONS
-- =========================================================

CREATE TABLE IF NOT EXISTS qualification_options (
    qualification VARCHAR(100) PRIMARY KEY,
    sort_order INT NOT NULL
);

INSERT IGNORE INTO qualification_options
    (qualification, sort_order)
VALUES
    ('MBBS', 1),
    ('BDS', 2),
    ('BAMS', 3),
    ('BHMS', 4),
    ('MD', 5),
    ('MS', 6),
    ('DNB', 7),
    ('DM', 8),
    ('MCh', 9),
    ('MDS', 10),
    ('PhD', 11),
    ('Other', 12);


-- =========================================================
-- 11. LANGUAGE OPTIONS
-- =========================================================

CREATE TABLE IF NOT EXISTS language_options (
    language VARCHAR(50) PRIMARY KEY,
    sort_order INT NOT NULL
);

INSERT IGNORE INTO language_options
    (language, sort_order)
VALUES
    ('English', 1),
    ('Hindi', 2),
    ('Telugu', 3),
    ('Tamil', 4),
    ('Kannada', 5),
    ('Malayalam', 6),
    ('Marathi', 7),
    ('Urdu', 8);
