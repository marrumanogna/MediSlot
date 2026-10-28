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