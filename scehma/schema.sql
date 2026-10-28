-- MediSlot Milestone 2 identity schema.
-- Runtime uses InnoDB, stores UTC timestamps, and never stores plaintext passwords.
CREATE TABLE IF NOT EXISTS users (
  user_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  email VARCHAR(254) NOT NULL,
  password_hash VARCHAR(255) NOT NULL,
  role ENUM('PATIENT','DOCTOR') NOT NULL,
  full_name VARCHAR(150) NOT NULL,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  PRIMARY KEY (user_id),
  UNIQUE KEY uq_users_email (email),
  KEY ix_users_role_active (role, is_active)
) ENGINE=InnoDB;
-- Doctor professional profiles.
-- Each profile belongs to an existing user with role DOCTOR.
CREATE TABLE IF NOT EXISTS doctor_profiles (
  user_id BIGINT UNSIGNED NOT NULL,
  specialization VARCHAR(120) NOT NULL,
  qualifications VARCHAR(500) NOT NULL,
  experience_years SMALLINT UNSIGNED NOT NULL DEFAULT 0,
  bio TEXT NULL,
  consultation_fee DECIMAL(10,2) NULL,
  photo_key VARCHAR(1024) NULL,
  timezone VARCHAR(64) NOT NULL DEFAULT 'UTC',
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
    ON UPDATE CURRENT_TIMESTAMP(6),
  PRIMARY KEY (user_id),
  CONSTRAINT fk_doctor_profiles_user
    FOREIGN KEY (user_id) REFERENCES users(user_id)
    ON DELETE CASCADE,
  CONSTRAINT chk_doctor_experience
    CHECK (experience_years <= 80),
  CONSTRAINT chk_doctor_fee
    CHECK (consultation_fee IS NULL OR consultation_fee >= 0)
) ENGINE=InnoDB;
-- Consultation types offered by doctors
CREATE TABLE IF NOT EXISTS consultation_types (
  consultation_type_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  doctor_id BIGINT UNSIGNED NOT NULL,
  name VARCHAR(120) NOT NULL,
  description VARCHAR(500) NULL,
  duration_minutes SMALLINT UNSIGNED NOT NULL DEFAULT 30,
  fee DECIMAL(10,2) NOT NULL DEFAULT 0.00,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
    ON UPDATE CURRENT_TIMESTAMP(6),
  PRIMARY KEY (consultation_type_id),
  UNIQUE KEY uq_consultation_type_doctor_name (doctor_id, name),
  CONSTRAINT fk_consultation_type_doctor
    FOREIGN KEY (doctor_id) REFERENCES doctor_profiles(user_id)
    ON DELETE CASCADE,
  CONSTRAINT chk_consultation_duration
    CHECK (duration_minutes BETWEEN 5 AND 480),
  CONSTRAINT chk_consultation_fee CHECK (fee >= 0)
) ENGINE=InnoDB;

-- Recurring weekly doctor availability
CREATE TABLE IF NOT EXISTS availability_patterns (
  pattern_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  doctor_id BIGINT UNSIGNED NOT NULL,
  day_of_week TINYINT UNSIGNED NOT NULL,
  start_time TIME NOT NULL,
  end_time TIME NOT NULL,
  timezone VARCHAR(64) NOT NULL DEFAULT 'UTC',
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
    ON UPDATE CURRENT_TIMESTAMP(6),
  PRIMARY KEY (pattern_id),
  KEY ix_availability_doctor_day (doctor_id, day_of_week, is_active),
  CONSTRAINT fk_availability_doctor
    FOREIGN KEY (doctor_id) REFERENCES doctor_profiles(user_id)
    ON DELETE CASCADE,
  CONSTRAINT chk_availability_day CHECK (day_of_week BETWEEN 0 AND 6),
  CONSTRAINT chk_availability_time CHECK (start_time < end_time)
) ENGINE=InnoDB;
-- Dates when a doctor is unavailable
CREATE TABLE IF NOT EXISTS doctor_blackout_dates (
  blackout_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  doctor_id BIGINT UNSIGNED NOT NULL,
  blackout_date DATE NOT NULL,
  reason VARCHAR(255) NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (blackout_id),
  UNIQUE KEY uq_doctor_blackout_date (doctor_id, blackout_date),
  CONSTRAINT fk_blackout_doctor
    FOREIGN KEY (doctor_id) REFERENCES doctor_profiles(user_id)
    ON DELETE CASCADE
) ENGINE=InnoDB;
-- Generated appointment slots
CREATE TABLE IF NOT EXISTS appointment_slots (
  slot_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  doctor_id BIGINT UNSIGNED NOT NULL,
  consultation_type_id BIGINT UNSIGNED NOT NULL,
  slot_start DATETIME NOT NULL,
  slot_end DATETIME NOT NULL,
  status ENUM('AVAILABLE','BOOKED','BLOCKED') NOT NULL DEFAULT 'AVAILABLE',
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (slot_id),
  UNIQUE KEY uq_doctor_slot (doctor_id, consultation_type_id, slot_start),
  KEY ix_slots_lookup (doctor_id, status, slot_start),
  CONSTRAINT fk_slot_doctor
    FOREIGN KEY (doctor_id) REFERENCES doctor_profiles(user_id)
    ON DELETE CASCADE,
  CONSTRAINT fk_slot_consultation_type
    FOREIGN KEY (consultation_type_id)
    REFERENCES consultation_types(consultation_type_id)
    ON DELETE CASCADE,
  CONSTRAINT chk_slot_time CHECK (slot_start < slot_end)
) ENGINE=InnoDB;
