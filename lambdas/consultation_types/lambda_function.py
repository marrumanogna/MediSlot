
import json
from common import config, dbconn, response, body


def handler(event, context):
    auth = (event.get("requestContext") or {}).get("authorizer") or {}
    if auth.get("role") != "DOCTOR" or not auth.get("userId"):
        return response(403, {"message": "Doctor access required"})

    try:
        doctor_id = int(auth["userId"])
        method = event.get("httpMethod", "GET").upper()
        path_params = event.get("pathParameters") or {}
        type_id = path_params.get("type_id")
        data = body(event) if method in ("POST", "PUT", "PATCH") else {}

        if method in ("POST", "PUT", "PATCH") and not isinstance(data, dict):
            return response(400, {"message": "Invalid JSON body"})

        c = config()
        conn = dbconn(c)

        try:
            with conn.cursor() as cur:
                if method == "GET":
                    if type_id:
                        cur.execute(
                            """SELECT consultation_type_id, name, description,
                                      duration_minutes, fee, is_active
                               FROM consultation_types
                               WHERE doctor_id=%s AND consultation_type_id=%s""",
                            (doctor_id, type_id),
                        )
                        row = cur.fetchone()
                        if not row:
                            return response(404, {"message": "Consultation type not found"})
                        row["fee"] = str(row["fee"])
                        return response(200, row)

                    cur.execute(
                        """SELECT consultation_type_id, name, description,
                                  duration_minutes, fee, is_active
                           FROM consultation_types
                           WHERE doctor_id=%s ORDER BY consultation_type_id""",
                        (doctor_id,),
                    )
                    rows = cur.fetchall()
                    for row in rows:
                        row["fee"] = str(row["fee"])
                    return response(200, {"items": rows})

                if method == "POST":
                    name = data.get("name")
                    duration = data.get("duration_minutes", 30)
                    fee = data.get("fee", 0)
                    if not isinstance(name, str) or not name.strip():
                        return response(400, {"message": "name is required"})
                    if not isinstance(duration, int) or not 5 <= duration <= 480:
                        return response(400, {"message": "duration_minutes must be 5-480"})
                    try:
                        fee = float(fee)
                        if fee < 0:
                            raise ValueError()
                    except (TypeError, ValueError):
                        return response(400, {"message": "fee must be non-negative"})
                    cur.execute(
                        """INSERT INTO consultation_types
                           (doctor_id, name, description, duration_minutes, fee)
                           VALUES (%s,%s,%s,%s,%s)""",
                        (doctor_id, name.strip(), data.get("description"), duration, fee),
                    )
                    conn.commit()
                    return response(201, {
                        "consultation_type_id": cur.lastrowid,
                        "message": "Consultation type created",
                    })

                if method in ("PUT", "PATCH"):
                    if not type_id:
                        return response(400, {"message": "type_id is required"})
                    cur.execute(
                        """SELECT name, description, duration_minutes, fee, is_active
                           FROM consultation_types
                           WHERE doctor_id=%s AND consultation_type_id=%s""",
                        (doctor_id, type_id),
                    )
                    old = cur.fetchone()
                    if not old:
                        return response(404, {"message": "Consultation type not found"})
                    merged = {**old, **data}
                    duration = merged["duration_minutes"]
                    fee = float(merged["fee"])
                    if not isinstance(merged["name"], str) or not merged["name"].strip():
                        return response(400, {"message": "name is required"})
                    if not isinstance(duration, int) or not 5 <= duration <= 480 or fee < 0:
                        return response(400, {"message": "Invalid duration or fee"})
                    cur.execute(
                        """UPDATE consultation_types
                           SET name=%s, description=%s, duration_minutes=%s,
                               fee=%s, is_active=%s
                           WHERE doctor_id=%s AND consultation_type_id=%s""",
                        (merged["name"].strip(), merged["description"], duration,
                         fee, merged["is_active"], doctor_id, type_id),
                    )
                    conn.commit()
                    return response(200, {"message": "Consultation type updated"})

                if method == "DELETE":
                    if not type_id:
                        return response(400, {"message": "type_id is required"})
                    cur.execute(
                        """DELETE FROM consultation_types
                           WHERE doctor_id=%s AND consultation_type_id=%s""",
                        (doctor_id, type_id),
                    )
                    conn.commit()
                    if cur.rowcount == 0:
                        return response(404, {"message": "Consultation type not found"})
                    return response(200, {"message": "Consultation type deleted"})

                return response(405, {"message": "Method not allowed"})
        finally:
            conn.close()

    except Exception:
        return response(500, {"message": "Internal server error"})
