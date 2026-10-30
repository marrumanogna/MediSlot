
import os
import re
import json
import bcrypt

from common import config, dbconn, body, response, emit, correlation


def handler(event, context):
    cid = correlation(event)
    conn = None

    try:
        role = os.environ["ROLE"]
        data = body(event)

        if not isinstance(data, dict):
            return response(400, {
                "message": "Invalid JSON body",
                "correlationId": cid
            })

        # -----------------------------
        # 1. Account details
        # -----------------------------
        first_name = str(data.get("firstName", "")).strip()
        last_name = str(data.get("lastName", "")).strip()
        email = str(data.get("email", "")).strip().lower()
        password = data.get("password", "")
        confirm_password = data.get("confirmPassword", "")

        min_len = int(
            __import__("common").get_param(
                f"/medislot/{os.environ.get('ENVIRONMENT', 'dev')}/auth/password-min-length"
            )
        )

        if (
            not first_name
            or len(first_name) > 100
            or not last_name
            or len(last_name) > 100
        ):
            return response(400, {
                "message": "First name and last name are required",
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

        if not isinstance(confirm_password, str) or password != confirm_password:
            return response(400, {
                "message": "Password and confirm password do not match",
                "correlationId": cid
            })

        # -----------------------------
        # 2. Doctor professional details
        # -----------------------------
        if role == "DOCTOR":

            licence_number = str(
                data.get("licenceNumber", "")
            ).strip()

            specialization = str(
                data.get("specialization", "")
            ).strip()

            qualifications = str(
                data.get("qualifications", "")
            ).strip()

            hospital_name = str(
                data.get("hospitalName", "")
            ).strip()

            hospital_address = str(
                data.get("hospitalAddress", "")
            ).strip()

            experience_years = data.get("experienceYears")

            languages_spoken = data.get("languagesSpoken")

            # Validate required text fields
            required_fields = {
                "licenceNumber": licence_number,
                "specialization": specialization,
                "qualifications": qualifications,
                "hospitalName": hospital_name,
                "hospitalAddress": hospital_address
            }

            missing_fields = [
                field for field, value in required_fields.items()
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
                or len(qualifications) > 500
                or len(hospital_name) > 200
                or len(hospital_address) > 500
            ):
                return response(400, {
                    "message": "One or more professional fields exceed the allowed length",
                    "correlationId": cid
                })

            # Validate experience
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

            # Validate languages
            if (
                not isinstance(languages_spoken, list)
                or not languages_spoken
                or not all(
                    isinstance(language, str) and language.strip()
                    for language in languages_spoken
                )
            ):
                return response(400, {
                    "message": "languagesSpoken must be a non-empty list of languages",
                    "correlationId": cid
                })

            languages_spoken = list(dict.fromkeys(
                language.strip()
                for language in languages_spoken
            ))

            # Existing optional fields retained
            consultation_fee = data.get("consultationFee")

            if consultation_fee is not None:
                try:
                    consultation_fee = float(consultation_fee)

                    if consultation_fee < 0:
                        raise ValueError()

                except (TypeError, ValueError):
                    return response(400, {
                        "message": "consultationFee must be a non-negative number",
                        "correlationId": cid
                    })

            timezone = str(data.get("timezone", "UTC")).strip()

        elif role == "PATIENT":
            return response(400, {
                "message": "Use the patient registration endpoint",
                "correlationId": cid
            })

        else:
            return response(500, {
                "message": "Invalid registration configuration",
                "correlationId": cid
            })

        # -----------------------------
        # 3. Hash password
        # -----------------------------
        hashed = bcrypt.hashpw(
            password.encode(),
            bcrypt.gensalt(rounds=12)
        ).decode()

        # -----------------------------
        # 4. Database connection
        # -----------------------------
        c = config()
        conn = dbconn(c)

        try:
            with conn.cursor() as cur:

                # Insert account details
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

                # Insert doctor professional profile
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
                        f"{first_name} {last_name}",
                        licence_number,
                        specialization,
                        qualifications,
                        experience_years,
                        hospital_name,
                        hospital_address,
                        json.dumps(languages_spoken),
                        data.get("bio"),
                        consultation_fee,
                        timezone
                    )
                )

            conn.commit()

        except Exception as e:
            conn.rollback()

            if "Duplicate entry" in str(e):
                return response(409, {
                    "message": "Email or licence number is already registered",
                    "correlationId": cid
                })

            raise

        finally:
            conn.close()
            conn = None

        # -----------------------------
        # 5. Success response
        # -----------------------------
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
            "message": "Doctor registration successful"
        })

    except Exception:
        if conn:
            conn.rollback()
            conn.close()

        emit("error", "registration_failed", cid)

        return response(500, {
            "message": "Internal server error",
            "correlationId": cid
        })
