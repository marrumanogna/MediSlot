
import logging

from common import config, dbconn, response, body

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def handler(event, context):
    auth = (event.get("requestContext") or {}).get("authorizer") or {}

    if auth.get("role") != "DOCTOR" or not auth.get("userId"):
        return response(403, {"message": "Doctor access required"})

    try:
        doctor_id = int(auth["userId"])
        method = (event.get("httpMethod") or "GET").upper()

        params = event.get("pathParameters") or {}
        pattern_id = params.get("pattern_id")

        data = body(event) if method in ("POST", "PUT", "PATCH") else {}

        if method in ("POST", "PUT", "PATCH") and not isinstance(data, dict):
            return response(400, {"message": "Invalid JSON body"})

        c = config()
        conn = dbconn(c)

        try:
            with conn.cursor() as cur:

                # GET: Fetch one pattern or list all patterns
                if method == "GET":

                    if pattern_id:
                        cur.execute(
                            """
                            SELECT pattern_id, day_of_week, start_time, end_time,
                                   timezone, is_active
                            FROM availability_patterns
                            WHERE doctor_id = %s AND pattern_id = %s
                            """,
                            (doctor_id, pattern_id),
                        )
                    else:
                        cur.execute(
                            """
                            SELECT pattern_id, day_of_week, start_time, end_time,
                                   timezone, is_active
                            FROM availability_patterns
                            WHERE doctor_id = %s
                            ORDER BY day_of_week, start_time
                            """,
                            (doctor_id,),
                        )

                    rows = cur.fetchall()

                    if pattern_id:
                        if not rows:
                            return response(
                                404,
                                {"message": "Availability pattern not found"},
                            )

                        result = dict(rows[0])

                        # Convert MySQL TIME values into JSON-compatible strings
                        for field in ("start_time", "end_time"):
                            if result.get(field) is not None:
                                result[field] = str(result[field])

                        return response(200, result)

                    # List response
                    items = []

                    for row in rows:
                        item = dict(row)

                        for field in ("start_time", "end_time"):
                            if item.get(field) is not None:
                                item[field] = str(item[field])

                        items.append(item)

                    return response(200, {"items": items})

                # POST, PUT and PATCH: Create or update patterns
                if method in ("POST", "PUT", "PATCH"):

                    if method == "POST":
                        merged = {
                            "day_of_week": data.get("day_of_week"),
                            "start_time": data.get("start_time"),
                            "end_time": data.get("end_time"),
                            "timezone": data.get("timezone", "UTC"),
                            "is_active": data.get("is_active", True),
                        }

                    else:
                        if not pattern_id:
                            return response(
                                400,
                                {"message": "pattern_id is required"},
                            )

                        cur.execute(
                            """
                            SELECT day_of_week, start_time, end_time,
                                   timezone, is_active
                            FROM availability_patterns
                            WHERE doctor_id = %s AND pattern_id = %s
                            """,
                            (doctor_id, pattern_id),
                        )

                        old = cur.fetchone()

                        if not old:
                            return response(
                                404,
                                {"message": "Availability pattern not found"},
                            )

                        merged = {**old, **data}

                    day = merged["day_of_week"]
                    start = str(merged["start_time"])
                    end = str(merged["end_time"])

                    if not isinstance(day, int) or not 0 <= day <= 6:
                        return response(
                            400,
                            {"message": "day_of_week must be 0-6 (Monday-Sunday)"},
                        )

                    if len(start) != 8 or len(end) != 8 or start >= end:
                        return response(
                            400,
                            {"message": "Use HH:MM:SS and ensure start_time < end_time"},
                        )

                    if method == "POST":
                        cur.execute(
                            """
                            INSERT INTO availability_patterns
                            (doctor_id, day_of_week, start_time, end_time,
                             timezone, is_active)
                            VALUES (%s, %s, %s, %s, %s, %s)
                            """,
                            (
                                doctor_id,
                                day,
                                start,
                                end,
                                merged["timezone"],
                                merged["is_active"],
                            ),
                        )

                        conn.commit()

                        return response(
                            201,
                            {
                                "pattern_id": cur.lastrowid,
                                "message": "Availability pattern created",
                            },
                        )

                    cur.execute(
                        """
                        UPDATE availability_patterns
                        SET day_of_week = %s,
                            start_time = %s,
                            end_time = %s,
                            timezone = %s,
                            is_active = %s
                        WHERE doctor_id = %s AND pattern_id = %s
                        """,
                        (
                            day,
                            start,
                            end,
                            merged["timezone"],
                            merged["is_active"],
                            doctor_id,
                            pattern_id,
                        ),
                    )

                    conn.commit()

                    return response(
                        200,
                        {"message": "Availability pattern updated"},
                    )

                # DELETE: Remove a pattern
                if method == "DELETE":

                    if not pattern_id:
                        return response(
                            400,
                            {"message": "pattern_id is required"},
                        )

                    cur.execute(
                        """
                        DELETE FROM availability_patterns
                        WHERE doctor_id = %s AND pattern_id = %s
                        """,
                        (doctor_id, pattern_id),
                    )

                    conn.commit()

                    if cur.rowcount == 0:
                        return response(
                            404,
                            {"message": "Availability pattern not found"},
                        )

                    return response(
                        200,
                        {"message": "Availability pattern deleted"},
                    )

                return response(405, {"message": "Method not allowed"})

        finally:
            conn.close()

    except Exception:
        logger.exception("Availability patterns Lambda failed")
        return response(500, {"message": "Internal server error"})
