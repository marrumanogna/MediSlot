
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from common import config, dbconn, response, correlation, emit


def authenticated_doctor(event):
    auth = (
        (event.get("requestContext") or {})
        .get("authorizer") or {}
    )

    try:
        user_id = int(auth.get("userId"))
    except (TypeError, ValueError):
        return None

    if user_id <= 0 or auth.get("role") != "DOCTOR":
        return None

    return user_id


def handler(event, context):
    cid = correlation(event)
    user_id = authenticated_doctor(event)

    if user_id is None:
        return response(403, {
            "message": "An authenticated doctor account is required",
            "correlationId": cid,
        })

    params = event.get("queryStringParameters") or {}
    requested_date = params.get("date")

    if not requested_date:
        return response(400, {
            "message": "date is required in YYYY-MM-DD format",
            "correlationId": cid,
        })

    try:
        day = date.fromisoformat(requested_date)
        if day.isoformat() != requested_date:
            raise ValueError
    except (TypeError, ValueError):
        return response(400, {
            "message": "date must use YYYY-MM-DD format",
            "correlationId": cid,
        })

    conn = None

    try:
        conn = dbconn(config())

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT dp.timezone
                FROM doctor_profiles dp
                JOIN users u ON u.user_id = dp.user_id
                WHERE dp.user_id = %s
                  AND u.role = 'DOCTOR'
                  AND u.is_active = TRUE
                """,
                (user_id,),
            )
            doctor = cur.fetchone()

            if not doctor:
                conn.rollback()
                return response(404, {
                    "message": "Active doctor profile not found",
                    "correlationId": cid,
                })

            try:
                timezone = ZoneInfo(doctor.get("timezone") or "UTC")
            except (ZoneInfoNotFoundError, ValueError, TypeError):
                conn.rollback()
                return response(500, {
                    "message": "Doctor timezone is invalid",
                    "correlationId": cid,
                })

            # Convert the doctor's local calendar day into a UTC range.
            local_start = datetime.combine(day, time.min).replace(
                tzinfo=timezone
            )
            local_end = datetime.combine(
                day + timedelta(days=1), time.min
            ).replace(tzinfo=timezone)

            utc_start = local_start.astimezone(ZoneInfo("UTC")).replace(
                tzinfo=None
            )
            utc_end = local_end.astimezone(ZoneInfo("UTC")).replace(
                tzinfo=None
            )

            cur.execute(
                """
                SELECT
                    s.slot_id,
                    s.consultation_type_id,
                    ct.name AS consultation_type,
                    s.slot_start,
                    s.slot_end,
                    s.status
                FROM appointment_slots s
                JOIN consultation_types ct
                  ON ct.consultation_type_id = s.consultation_type_id
                WHERE s.doctor_id = %s
                  AND s.slot_start >= %s
                  AND s.slot_start < %s
                ORDER BY s.slot_start
                """,
                (user_id, utc_start, utc_end),
            )
            slots = cur.fetchall()

        conn.rollback()

        result = []
        for slot in slots:
            start_utc = slot["slot_start"].replace(tzinfo=ZoneInfo("UTC"))
            end_utc = slot["slot_end"].replace(tzinfo=ZoneInfo("UTC"))

            result.append({
                "slot_id": int(slot["slot_id"]),
                "consultation_type_id": int(
                    slot["consultation_type_id"]
                ),
                "consultation_type": slot["consultation_type"],
                "slot_start": start_utc.astimezone(timezone).isoformat(),
                "slot_end": end_utc.astimezone(timezone).isoformat(),
                "status": slot["status"],
            })

        return response(200, {
            "doctor_id": user_id,
            "date": day.isoformat(),
            "timezone": str(timezone),
            "slots": result,
            "count": len(result),
        })

    except Exception:
        emit(
            "error",
            "doctor_schedule_failed",
            cid,
            userId=str(user_id),
        )
        return response(500, {
            "message": "Unable to retrieve doctor schedule",
            "correlationId": cid,
        })

    finally:
        if conn is not None:
            conn.close()
