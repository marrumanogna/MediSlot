
import logging
from datetime import date

from common import config, dbconn, response, body

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def handler(event, context):
    # Get authenticated doctor details from API Gateway authorizer
    auth = (
        (event.get("requestContext") or {}).get("authorizer") or {}
    )

    if auth.get("role") != "DOCTOR" or not auth.get("userId"):
        return response(403, {
            "message": "Doctor access required"
        })

    conn = None

    try:
        doctor_id = int(auth["userId"])

        # Get HTTP method (REST API and HTTP API compatible)
        method = (
            event.get("httpMethod")
            or (event.get("requestContext", {}).get("http") or {}).get("method")
            or "GET"
        ).upper()

        params = event.get("pathParameters") or {}
        blackout_id = params.get("blackout_id")

        # Validate blackout ID
        if blackout_id is not None:
            try:
                blackout_id = int(blackout_id)
                if blackout_id <= 0:
                    raise ValueError
            except (TypeError, ValueError):
                return response(400, {
                    "message": "Invalid blackout_id"
                })

        # Read request body
        data = {}

        if method in ("POST", "PUT"):
            try:
                data = body(event)
            except (ValueError, TypeError):
                return response(400, {
                    "message": "Invalid JSON body"
                })

            if not isinstance(data, dict):
                return response(400, {
                    "message": "Request body must be a JSON object"
                })

            # Validate blackout date
            blackout_date = data.get("blackout_date")

            try:
                parsed_date = date.fromisoformat(blackout_date)

                if parsed_date.isoformat() != blackout_date:
                    raise ValueError

            except (TypeError, ValueError):
                return response(400, {
                    "message": "blackout_date must use YYYY-MM-DD format"
                })

            # Validate reason
            reason = data.get("reason")

            if reason is not None:
                if not isinstance(reason, str) or len(reason) > 255:
                    return response(400, {
                        "message": "reason must be 255 characters or fewer"
                    })

                reason = reason.strip() or None

        # Validate supported methods
        if method not in ("GET", "POST", "PUT", "DELETE"):
            return response(405, {
                "message": "Method not allowed"
            })

        # Validate path parameters
        if method in ("PUT", "DELETE") and not blackout_id:
            return response(400, {
                "message": "blackout_id is required"
            })

        c = config()
        conn = dbconn(c)

        with conn.cursor() as cur:

            # --------------------------------
            # GET ALL BLACKOUT DATES
            # --------------------------------
            if method == "GET" and not blackout_id:

                cur.execute(
                    """
                    SELECT blackout_id, blackout_date, reason, created_at
                    FROM doctor_blackout_dates
                    WHERE doctor_id = %s
                    ORDER BY blackout_date
                    """,
                    (doctor_id,)
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

                return response(200, {
                    "blackout_dates": rows
                })

            # --------------------------------
            # GET BLACKOUT DATE BY ID
            # --------------------------------
            if method == "GET" and blackout_id:

                cur.execute(
                    """
                    SELECT blackout_id, blackout_date, reason, created_at
                    FROM doctor_blackout_dates
                    WHERE doctor_id = %s
                    AND blackout_id = %s
                    """,
                    (doctor_id, blackout_id)
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

            # --------------------------------
            # POST CREATE BLACKOUT DATE
            # --------------------------------
            if method == "POST":

                cur.execute(
                    """
                    INSERT INTO doctor_blackout_dates
                    (doctor_id, blackout_date, reason)
                    VALUES (%s, %s, %s)
                    """,
                    (doctor_id, blackout_date, reason)
                )

                conn.commit()

                return response(201, {
                    "message": "Blackout date created successfully",
                    "blackout_id": cur.lastrowid,
                    "blackout_date": blackout_date,
                    "reason": reason
                })

            # --------------------------------
            # PUT UPDATE BLACKOUT DATE
            # --------------------------------
            if method == "PUT" and blackout_id:

                # Check whether the blackout date exists
                # and belongs to the authenticated doctor
                cur.execute(
                    """
                    SELECT blackout_id
                    FROM doctor_blackout_dates
                    WHERE doctor_id = %s
                    AND blackout_id = %s
                    """,
                    (doctor_id, blackout_id)
                )

                existing = cur.fetchone()

                if not existing:
                    return response(404, {
                        "message": "Blackout date not found"
                    })

                # Update existing blackout date
                cur.execute(
                    """
                    UPDATE doctor_blackout_dates
                    SET blackout_date = %s,
                        reason = %s
                    WHERE doctor_id = %s
                    AND blackout_id = %s
                    """,
                    (
                        blackout_date,
                        reason,
                        doctor_id,
                        blackout_id
                    )
                )

                conn.commit()

                return response(200, {
                    "message": "Blackout date updated successfully",
                    "blackout_id": blackout_id,
                    "blackout_date": blackout_date,
                    "reason": reason
                })

            # --------------------------------
            # DELETE BLACKOUT DATE
            # --------------------------------
            if method == "DELETE" and blackout_id:

                cur.execute(
                    """
                    DELETE FROM doctor_blackout_dates
                    WHERE doctor_id = %s
                    AND blackout_id = %s
                    """,
                    (doctor_id, blackout_id)
                )

                if cur.rowcount == 0:
                    return response(404, {
                        "message": "Blackout date not found"
                    })

                conn.commit()

                return response(200, {
                    "message": "Blackout date deleted successfully",
                    "blackout_id": blackout_id
                })

    except Exception:
        if conn:
            conn.rollback()

        logger.exception("Blackout dates Lambda failed")

        return response(500, {
            "message": "Internal server error"
        })

    finally:
        if conn:
            conn.close()
