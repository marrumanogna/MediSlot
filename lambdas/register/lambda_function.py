
import os
import re
import json
import bcrypt

from common import config, dbconn, body, response, emit, correlation


def handler(event, context):
    cid = correlation(event)
    conn = None

    try:
        role = os.environ["ROLE"].upper()
        data = body(event)

        if role not in ("DOCTOR", "PATIENT"):
            return response(500, {
                "message": "Invalid registration configuration",
                "correlationId": cid
            })

        if not isinstance(data, dict):
            return response(400, {
                "message": "Invalid JSON body",
                "correlationId": cid
            })

        # 1. Account details
        first_name = str(data.get("firstName", "")).strip()
        last_name = str(data.get("lastName", "")).strip()
        full_name = f"{first_name} {last_name}".strip()

        email = str(data.get("email", "")).strip().lower()
        password = data.get("password", "")
        confirm_password = data.get("confirmPassword", "")

        if (
            not first_name or len(first_name) > 100
            or not last_name or len(last_name) > 100
            or len(full_name) > 150
        ):
            return response(400, {
                "message": "Valid first name and last name are required",
                "correlationId": cid
            })

        if (
            not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email)
            or len(email) > 254
        ):
            return response(400, {
                "message": "A valid email address is required",
                "correlationId": cid
            })

        min_len = int(
            __import__("common").get_param(
                f"/medislot/{os.environ.get('ENVIRONMENT', 'dev')}/auth/password-min-length"
            )
        )

        if (
            not isinstance(password, str)
            or len(password) < min_len
            or len(password.encode()) > 72
            or not re.search(r"[A-Za-z]", password)
            or not re.search(r"\d", password)
        ):
            return response(400, {
                "message": (
                    f"Password must be at least {min_len} characters "
                    "and contain at least one letter and one digit"
                ),
                "correlationId": cid
            })

        if (
            not isinstance(confirm_password, str)
            or password != confirm_password
        ):
            return response(400, {
                "message": "Password and confirm password do not match",
                "correlationId": cid
            })

        # 2. Prepare role-specific details
        if role == "DOCTOR":

            licence_number = str(
                data.get("licenceNumber", "")
            ).strip()

            specialization = str(
                data.get("specialization", "")
            ).strip()

            qualifications = data.get("qualifications", [])

            # Accept either an array or comma-separated text
            if isinstance(qualifications, str):
                qualifications = [
                    item.strip()
                    for item in qualifications.split(",")
                    if item.strip()
                ]

            if not isinstance(qualifications, list):
                return response(400, {
                    "message": "Qualifications must be a list",
                    "correlationId": cid
                })

            qualifications = list(dict.fromkeys(
                item.strip()
                for item in qualifications
                if isinstance(item, str) and item.strip()
            ))

            hospital_name = str(
                data.get("hospitalName", "")
            ).strip()

            hospital_address = str(
                data.get("hospitalAddress", "")
            ).strip()

            languages_spoken = data.get("languagesSpoken")

            required_fields = {
                "licenceNumber": licence_number,
                "specialization": specialization,
                "qualifications": qualifications,
                "hospitalName": hospital_name,
                "hospitalAddress": hospital_address
            }

            missing_fields = [
                key for key, value in required_fields.items()
                if not value
            ]

            if missing_fields:
                return response(400, {
                    "message": "All professional details are required",
                    "missingFields": missing_fields,
                    "correlationId": cid
                })

            if (
                len(licence_number) > 100
                or len(specialization) > 120
                or len(hospital_name) > 200
                or len(hospital_address) > 500
                or len(json.dumps(qualifications)) > 10000
            ):
                return response(400, {
                    "message": "One or more professional fields exceed allowed limits",
                    "correlationId": cid
                })

            experience_years = data.get("experienceYears")

            if (
                isinstance(experience_years, bool)
                or experience_years is None
                or not str(experience_years).isdigit()
                or int(experience_years) > 80
            ):
                return response(400, {
                    "message": "experienceYears must be between 0 and 80",
                    "correlationId": cid
                })

            experience_years = int(experience_years)

            if (
                not isinstance(languages_spoken, list)
                or not languages_spoken
                or not all(
                    isinstance(language, str) and language.strip()
                    for language in languages_spoken
                )
            ):
                return response(400, {
                    "message": "languagesSpoken must be a non-empty list",
                    "correlationId": cid
                })

            languages_spoken = list(dict.fromkeys(
                language.strip() for language in languages_spoken
            ))

            consultation_fee = data.get("consultationFee")

            if consultation_fee is not None:
                try:
                    consultation_fee = float(consultation_fee)
                    if consultation_fee < 0:
                        raise ValueError()
                except (TypeError, ValueError):
                    return response(400, {
                        "message": "consultationFee must be non-negative",
                        "correlationId": cid
                    })

            timezone = str(data.get("timezone", "UTC")).strip()

            bio = data.get("bio")

            if bio is not None and not isinstance(bio, str):
                return response(400, {
                    "message": "bio must be text",
                    "correlationId": cid
                })

        else:
            # PATIENT details
            date_of_birth = data.get("dateOfBirth") or None
            gender = data.get("gender") or None
            phone = data.get("phone") or None
            address = data.get("address") or None
            city = data.get("city") or None
            emergency_contact = data.get("emergencyContact") or None

            if gender is not None and len(str(gender)) > 20:
                return response(400, {
                    "message": "Gender exceeds allowed length",
                    "correlationId": cid
                })

            if phone is not None and len(str(phone)) > 20:
                return response(400, {
                    "message": "Phone exceeds allowed length",
                    "correlationId": cid
                })

            if emergency_contact is not None and len(str(emergency_contact)) > 20:
                return response(400, {
                    "message": "Emergency contact exceeds allowed length",
                    "correlationId": cid
                })

        # 3. Hash password
        hashed = bcrypt.hashpw(
            password.encode(),
            bcrypt.gensalt(rounds=12)
        ).decode()

        # 4. Connect to database
        conn = dbconn(config())

        with conn.cursor() as cur:

            # Insert account details using the existing users schema.
            # first_name and last_name are separate columns.
            cur.execute(
                """
                INSERT INTO users
                (
                    first_name,
                    last_name,
                    email,
                    password_hash,
                    role
                )
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    first_name,
                    last_name,
                    email,
                    hashed,
                    role
                )
            )

            uid = cur.lastrowid

            if role == "DOCTOR":

                cur.execute(
                    """
                    INSERT INTO doctor_profiles
                    (
                        user_id,
                        full_name,
                        licence_number,
                        specialization,
                        qualifications,
                        experience_years,
                        hospital_name,
                        hospital_address,
                        languages_spoken,
                        bio,
                        consultation_fee,
                        timezone
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        uid,
                        full_name,
                        licence_number,
                        specialization,
                        json.dumps(qualifications),
                        experience_years,
                        hospital_name,
                        hospital_address,
                        json.dumps(languages_spoken),
                        bio,
                        consultation_fee,
                        timezone
                    )
                )

            else:

                cur.execute(
                    """
                    INSERT INTO patients
                    (
                        user_id,
                        full_name,
                        date_of_birth,
                        gender,
                        phone,
                        address,
                        city,
                        emergency_contact
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        uid,
                        full_name,
                        date_of_birth,
                        gender,
                        phone,
                        address,
                        city,
                        emergency_contact
                    )
                )

        conn.commit()

        emit(
            "info",
            "registration_succeeded",
            cid,
            role=role,
            userId=str(uid)
        )

        return response(201, {
            "userId": str(uid),
            "role": role,
            "message": f"{role.title()} registration successful"
        })

    except Exception as e:

        if conn:
            try:
                conn.rollback()
            except Exception:
                pass

        print(
            f"REGISTRATION ERROR: {type(e).__name__}: {str(e)}"
        )

        if "Duplicate entry" in str(e):
            return response(409, {
                "message": "Email or licence number is already registered",
                "correlationId": cid
            })

        emit("error", "registration_failed", cid)

        return response(500, {
            "message": "Internal server error",
            "correlationId": cid
        })

    finally:
        if conn:
            conn.close()
