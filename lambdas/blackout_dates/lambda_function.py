import logging
from datetime import date

from common import config, dbconn, response, body

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def handler(event, context):
    auth = (event.get("requestContext") or {}).get("authorizer") or {}

    if auth.get("role") != "DOCTOR" or not auth.get("userId"):
        return response(403, {"message": "Doctor access required"})

    try:
        doctor_id = int(auth["userId"])
        method = event.get("httpMethod", "GET").upper()
        params = event.get("pathParameters") or {}
        blackout_id = params.get("blackout_id")

        data = body(event) if method in ("POST", "PUT") else {}

        # Validate POST and PUT request bodies
        if method in ("POST", "PUT"):
            if not isinstance(data, dict):
                return response(400, {"message": "Invalid JSON body"})

            if method == "PUT" and not blackout_id:
                return response(400, {"message": "blackout_id is required"})

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

                # GET all blackout dates
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
                            row["blackout_date"] = (
                                row["blackout_date"].isoformat()
                            )
                        if row.get("created_at"):
                            row["created_at"] = (
                                row["created_at"].isoformat()
                            )

                    return response(200, {"blackout_dates": rows})

                # GET blackout date by ID
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
                        return response(404, {
                            "message": "Blackout date not found"
                        })

                    if row.get("blackout_date"):
                        row["blackout_date"] = (
                            row["blackout_date"].isoformat()
                        )
                    if row.get("created_at"):
                        row["created_at"] = (
                            row["created_at"].isoformat()
                        )

                    return response(200, row)

                # POST create blackout date
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

                # PUT update blackout date
                if method == "PUT" and blackout_id:
                    # Check that this blackout date belongs to the doctor
                    cur.execute(
                        """
                        SELECT blackout_id
                        FROM doctor_blackout_dates
                        WHERE doctor_id = %s AND blackout_id = %s
                        """,
                        (doctor_id, blackout_id),
                    )

                    existing = cur.fetchone()

                    if not existing:
                        return response(404, {
                            "message": "Blackout date not found"
                        })

                    cur.execute(
                        """
                        UPDATE doctor_blackout_dates
                        SET blackout_date = %s, reason = %s
                        WHERE doctor_id = %s AND blackout_id = %s
                        """,
                        (blackout_date, reason, doctor_id, blackout_id),
                    )

                    conn.commit()

                    return response(200, {
                        "message": "Blackout date updated",
                        "blackout_id": int(blackout_id),
                        "blackout_date": blackout_date,
                        "reason": reason,
                    })

                # DELETE blackout date
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
                        return response(404, {
                            "message": "Blackout date not found"
                        })

                    return response(200, {
                        "message": "Blackout date deleted"
                    })

                return response(405, {
                    "message": "Method not allowed"
                })

        finally:
            conn.close()

    except Exception:
        logger.exception("Blackout dates Lambda failed")
        return response(500, {
            "message": "Internal server error"
        })