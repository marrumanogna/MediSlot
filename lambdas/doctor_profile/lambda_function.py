import os
import uuid
import boto3
from decimal import Decimal, InvalidOperation
from botocore.exceptions import ClientError
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from common import config, dbconn, body, response, emit, correlation

s3 = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-east-1"))

PROFILE_FIELDS = {
    "specialization": 120,
    "qualifications": 500,
    "bio": 5000,
}

REQUIRED_FIELDS = {"specialization", "qualifications"}

ALLOWED_FIELDS = {
    "specialization",
    "qualifications",
    "experience_years",
    "bio",
    "consultation_fee",
    "timezone",
    "photo_key",
}

MAX_PHOTO_BYTES = 5 * 1024 * 1024
PHOTO_TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}


def authenticated_user(event):
    auth = (
        event.get("requestContext", {})
        .get("authorizer", {})
    )

    user_id = auth.get("userId")
    role = auth.get("role")

    if not user_id or role != "DOCTOR":
        return None

    try:
        parsed_id = int(user_id)
        return parsed_id if parsed_id > 0 else None
    except (TypeError, ValueError):
        return None


def validate_profile_data(data, method, cid):
    """Validate profile fields before any database write."""

    unsupported = set(data) - ALLOWED_FIELDS
    if unsupported:
        return None, response(400, {
            "message": "Request contains unsupported fields",
            "correlationId": cid,
        })

    if method in ("POST", "PUT"):
        missing = REQUIRED_FIELDS - set(data)
        if missing:
            return None, response(400, {
                "message": (
                    "specialization and qualifications are required"
                ),
                "correlationId": cid,
            })

    if method == "PATCH" and not data:
        return None, response(400, {
            "message": "At least one field is required",
            "correlationId": cid,
        })

    values = {}

    for field, limit in PROFILE_FIELDS.items():
        if field not in data:
            continue

        value = data[field]

        if field in REQUIRED_FIELDS:
            if not isinstance(value, str) or not value.strip():
                return None, response(400, {
                    "message": (
                        f"{field} is required and cannot be empty"
                    ),
                    "correlationId": cid,
                })

        if field == "bio" and value is not None:
            if not isinstance(value, str):
                return None, response(400, {
                    "message": "Invalid bio",
                    "correlationId": cid,
                })

        if value is not None:
            if not isinstance(value, str) or len(value.strip()) > limit:
                return None, response(400, {
                    "message": f"Invalid {field}",
                    "correlationId": cid,
                })

            value = value.strip()

        values[field] = value

    if "experience_years" in data:
        value = data["experience_years"]

        if type(value) is not int or not 0 <= value <= 80:
            return None, response(400, {
                "message": (
                    "experience_years must be an integer from 0 to 80"
                ),
                "correlationId": cid,
            })

        values["experience_years"] = value

    if "consultation_fee" in data:
        value = data["consultation_fee"]

        # Reject booleans, which Decimal("True") cannot represent.
        if isinstance(value, bool) or value is None:
            return None, response(400, {
                "message": (
                    "consultation_fee must be a non-negative amount"
                ),
                "correlationId": cid,
            })

        try:
            fee = Decimal(str(value))

            if (
                not fee.is_finite()
                or fee < 0
                or fee > Decimal("99999999.99")
                or fee.as_tuple().exponent < -2
            ):
                raise InvalidOperation

            values["consultation_fee"] = fee

        except (InvalidOperation, ValueError, TypeError):
            return None, response(400, {
                "message": (
                    "consultation_fee must be a non-negative amount "
                    "with at most two decimal places"
                ),
                "correlationId": cid,
            })

    if "timezone" in data:
        value = data["timezone"]

        if not isinstance(value, str) or not value.strip():
            return None, response(400, {
                "message": "timezone must be an IANA timezone name",
                "correlationId": cid,
            })

        value = value.strip()

        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            return None, response(400, {
                "message": "Unknown timezone",
                "correlationId": cid,
            })

        values["timezone"] = value

    if "photo_key" in data:
        value = data["photo_key"]
        if value is not None and (not isinstance(value, str) or not value.strip()):
            return None, response(400, {
                "message": "photo_key must be a valid uploaded photo key or null",
                "correlationId": cid,
            })
        values["photo_key"] = value.strip() if isinstance(value, str) else None

    if method in ("POST", "PUT"):
        values.setdefault("experience_years", 0)
        values.setdefault("bio", None)
        values.setdefault("consultation_fee", None)
        values.setdefault("timezone", "UTC")

    return values, None


def handler(event, context):
    cid = correlation(event)
    method = event.get("httpMethod", "").upper()
    user_id = authenticated_user(event)

    if user_id is None:
        return response(403, {
            "message": "A valid authenticated doctor account is required",
            "correlationId": cid,
        })

    path = (event.get("path") or event.get("resource") or "").rstrip("/")
    is_photo_upload_route = path.endswith("/doctor/profile/photo-upload-url")
    supported_methods = ("GET", "POST", "PUT", "PATCH", "DELETE")

    if method not in supported_methods:
        return response(405, {
            "message": "Method not allowed",
            "correlationId": cid,
        })

    if is_photo_upload_route and method != "POST":
        return response(405, {
            "message": "Method not allowed",
            "correlationId": cid,
        })

    data = body(event) if (method in ("POST", "PUT", "PATCH") and (not is_photo_upload_route or method == "POST")) else {}

    if method in ("POST", "PUT", "PATCH") and not isinstance(data, dict):
        return response(400, {
            "message": "Invalid JSON body",
            "correlationId": cid,
        })

    values = {}

    if method in ("POST", "PUT", "PATCH") and not is_photo_upload_route:
        values, error = validate_profile_data(data, method, cid)
        if error:
            return error

    conn = None

    try:
        # config() retrieves the existing DB and JWT SSM parameters.
        # The Lambda execution role must permit these parameter reads.
        c = config()
        conn = dbconn(c)

        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT user_id, full_name, email
                    FROM users
                    WHERE user_id = %s
                      AND role = 'DOCTOR'
                      AND is_active = TRUE
                    """,
                    (user_id,),
                )
                doctor = cur.fetchone()

                if not doctor:
                    conn.rollback()
                    return response(404, {
                        "message": "Active doctor account not found",
                        "correlationId": cid,
                    })

                if is_photo_upload_route:
                    content_type = data.get("content_type")
                    extension = PHOTO_TYPES.get(content_type)
                    content_length = data.get("content_length")
                    bucket = os.environ.get("DOCTOR_PHOTOS_BUCKET")

                    if not extension:
                        conn.rollback()
                        return response(400, {
                            "message": "content_type must be image/jpeg, image/png, or image/webp",
                            "correlationId": cid,
                        })
                    if type(content_length) is not int or not 1 <= content_length <= MAX_PHOTO_BYTES:
                        conn.rollback()
                        return response(400, {
                            "message": "content_length must be an integer between 1 and 5242880",
                            "correlationId": cid,
                        })
                    if not bucket:
                        conn.rollback()
                        emit("error", "doctor_photo_bucket_not_configured", cid)
                        return response(500, {
                            "message": "Photo storage is not configured",
                            "correlationId": cid,
                        })

                    photo_key = f"doctors/{user_id}/{uuid.uuid4().hex}.{extension}"
                    upload_url = s3.generate_presigned_url(
                        "put_object",
                        Params={
                            "Bucket": bucket,
                            "Key": photo_key,
                            "ContentType": content_type,
                            "ContentLength": content_length,
                        },
                        ExpiresIn=300,
                        HttpMethod="PUT",
                    )
                    conn.rollback()
                    return response(200, {
                        "upload_url": upload_url,
                        "photo_key": photo_key,
                        "expires_in_seconds": 300,
                        "max_size_bytes": MAX_PHOTO_BYTES,
                        "required_headers": {
                            "Content-Type": content_type,
                            "Content-Length": str(content_length),
                        },
                        "next_step": "PUT the image bytes to upload_url, then PATCH /doctor/profile with photo_key",
                    })

                if method == "DELETE":
                    cur.execute(
                        "SELECT photo_key FROM doctor_profiles WHERE user_id = %s",
                        (user_id,),
                    )
                    existing_profile = cur.fetchone()
                    if not existing_profile:
                        conn.rollback()
                        return response(404, {
                            "message": "Doctor profile not found",
                            "correlationId": cid,
                        })
                    photo_key_to_delete = existing_profile.get("photo_key")
                    cur.execute(
                        "DELETE FROM doctor_profiles WHERE user_id = %s",
                        (user_id,),
                    )
                    conn.commit()
                    if photo_key_to_delete and os.environ.get("DOCTOR_PHOTOS_BUCKET"):
                        try:
                            s3.delete_object(
                                Bucket=os.environ["DOCTOR_PHOTOS_BUCKET"],
                                Key=photo_key_to_delete,
                            )
                        except Exception:
                            emit("warning", "doctor_profile_photo_cleanup_failed", cid, userId=str(user_id))
                    emit("info", "doctor_profile_deleted", cid, userId=str(user_id))
                    return response(200, {
                        "message": "Doctor profile deleted",
                        "userId": str(user_id),
                    })

                if "photo_key" in values and values["photo_key"] is not None:
                    photo_key = values["photo_key"]
                    expected_prefix = f"doctors/{user_id}/"
                    bucket = os.environ.get("DOCTOR_PHOTOS_BUCKET")
                    if not photo_key.startswith(expected_prefix) or not bucket:
                        conn.rollback()
                        return response(400, {
                            "message": "photo_key must refer to an uploaded photo belonging to your account",
                            "correlationId": cid,
                        })
                    try:
                        photo_head = s3.head_object(Bucket=bucket, Key=photo_key)
                    except ClientError:
                        conn.rollback()
                        return response(400, {
                            "message": "Photo was not found in storage; upload it before saving photo_key",
                            "correlationId": cid,
                        })
                    if photo_head.get("ContentLength", 0) > MAX_PHOTO_BYTES or photo_head.get("ContentType") not in PHOTO_TYPES:
                        conn.rollback()
                        return response(400, {
                            "message": "Uploaded photo must be JPEG, PNG, or WebP and at most 5 MB",
                            "correlationId": cid,
                        })

                if method == "GET":
                    cur.execute(
                        """
                        SELECT specialization, qualifications,
                               experience_years, bio, consultation_fee,
                               photo_key, timezone, created_at, updated_at
                        FROM doctor_profiles
                        WHERE user_id = %s
                        """,
                        (user_id,),
                    )
                    profile = cur.fetchone()

                    if not profile:
                        conn.rollback()
                        return response(404, {
                            "message": "Doctor profile not found",
                            "correlationId": cid,
                        })

                    result = {
                        **doctor,
                        **profile,
                    }

                    for key in ("created_at", "updated_at"):
                        if result.get(key):
                            result[key] = result[key].isoformat()

                    if result.get("consultation_fee") is not None:
                        result["consultation_fee"] = str(
                            result["consultation_fee"]
                        )

                    conn.rollback()  # End the read transaction.
                    return response(200, result)

                cur.execute(
                    """
                    SELECT user_id
                    FROM doctor_profiles
                    WHERE user_id = %s
                    """,
                    (user_id,),
                )
                exists = cur.fetchone() is not None

                if method == "POST" and exists:
                    conn.rollback()
                    return response(409, {
                        "message": (
                            "Doctor profile already exists; use PUT "
                            "or PATCH to update"
                        ),
                        "correlationId": cid,
                    })

                if method in ("PUT", "PATCH") and not exists:
                    conn.rollback()
                    return response(404, {
                        "message": (
                            "Doctor profile does not exist; use POST "
                            "to create it"
                        ),
                        "correlationId": cid,
                    })

                if method == "POST":
                    columns = ["user_id", *values.keys()]
                    params = [user_id, *values.values()]
                    placeholders = ", ".join(["%s"] * len(columns))

                    cur.execute(
                        f"INSERT INTO doctor_profiles "
                        f"({', '.join(columns)}) "
                        f"VALUES ({placeholders})",
                        params,
                    )

                else:
                    if not values:
                        conn.rollback()
                        return response(400, {
                            "message": "No profile fields supplied",
                            "correlationId": cid,
                        })

                    assignments = ", ".join(
                        f"{field} = %s" for field in values
                    )

                    cur.execute(
                        f"UPDATE doctor_profiles "
                        f"SET {assignments} WHERE user_id = %s",
                        [*values.values(), user_id],
                    )

            conn.commit()

        except Exception:
            conn.rollback()
            raise

        emit(
            "info",
            "doctor_profile_saved",
            cid,
            userId=str(user_id),
            method=method,
        )

        return response(
            201 if method == "POST" else 200,
            {
                "message": (
                    "Doctor profile created"
                    if method == "POST"
                    else "Doctor profile updated"
                ),
                "userId": str(user_id),
            },
        )

    except Exception:
        emit(
            "error",
            "doctor_profile_failed",
            cid,
            method=method,
            userId=str(user_id),
        )

        return response(500, {
            "message": "Internal server error",
            "correlationId": cid,
        })

    finally:
        if conn is not None:
            conn.close()
