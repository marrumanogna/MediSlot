
from datetime import date
from common import config, dbconn, response, body


def handler(event, context):
    auth = (event.get("requestContext") or {}).get("authorizer") or {}
    if auth.get("role") != "DOCTOR" or not auth.get("userId"):
        return response(403, {"message": "Doctor access required"})

    try:
        doctor_id = int(auth["userId"])
        method = event.get("httpMethod", "GET").upper()
        params = event.get("pathParameters") or {}
        blackout_id = params.get("blackout_id")
        data = body(event) if method == "POST" else {}

        if method == "POST":
            if not isinstance(data, dict):
                return response(400, {"message": "Invalid JSON body"})

            blackout_date = data.get("blackout_date")
            reason = data.get("reason")

            try:
                parsed_date = date.fromisoformat(blackout_date)
                if parsed_date.isoformat() != blackout_date:
                    raise ValueError
            except (TypeError, ValueError):
                return response(400, {
                    "message": "blackout_date must use YYYY-MM-DD format"
                })

            if reason is not None and (
                not isinstance(reason, str) or len(reason) > 255
            ):
                return response(400, {
                    "message": "reason must be 255 characters or fewer"
                })

        c = config()
        conn = dbconn(c)
        try:
            with conn.cursor() as cur:
                if method == "GET" and not blackout_id:
                    cur.execute(
                        """
                        SELECT blackout_id, blackout_date, reason, created_at
                        FROM doctor_blackout_dates
                        WHERE doctor_id = %s
                        ORDER BY blackout_date
                        """,
                        (doctor_id,),
                    )
                    rows = cur.fetchall()
                    for row in rows:
                        if row.get("blackout_date"):
                            row["blackout_date"] = row["blackout_date"].isoformat()
                        if row.get("created_at"):
                            row["created_at"] = row["created_at"].isoformat()
                    return response(200, {"blackout_dates": rows})

                if method == "GET" and blackout_id:
                    cur.execute(
                        """
                        SELECT blackout_id, blackout_date, reason, created_at
                        FROM doctor_blackout_dates
                        WHERE doctor_id = %s AND blackout_id = %s
                        """,
                        (doctor_id, blackout_id),
                    )
                    row = cur.fetchone()
                    if not row:
                        return response(404, {"message": "Blackout date not found"})
                    if row.get("blackout_date"):
                        row["blackout_date"] = row["blackout_date"].isoformat()
                    if row.get("created_at"):
                        row["created_at"] = row["created_at"].isoformat()
                    return response(200, row)

                if method == "POST":
                    cur.execute(
                        """
                        INSERT INTO doctor_blackout_dates
                            (doctor_id, blackout_date, reason)
                        VALUES (%s, %s, %s)
                        """,
                        (doctor_id, blackout_date, reason),
                    )
                    conn.commit()
                    return response(201, {
                        "blackout_id": cur.lastrowid,
                        "blackout_date": blackout_date,
                        "reason": reason,
                    })

                if method == "DELETE" and blackout_id:
                    cur.execute(
                        """
                        DELETE FROM doctor_blackout_dates
                        WHERE doctor_id = %s AND blackout_id = %s
                        """,
                        (doctor_id, blackout_id),
                    )
                    conn.commit()
                    if cur.rowcount == 0:
                        return response(404, {"message": "Blackout date not found"})
                    return response(200, {"message": "Blackout date deleted"})

                return response(405, {"message": "Method not allowed"})
        finally:
            conn.close()
    except Exception:
        return response(500, {"message": "Internal server error"})
