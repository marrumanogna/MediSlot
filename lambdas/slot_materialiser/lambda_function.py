from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from common import config, dbconn, response


def handler(event, context):
    """
    Generate appointment slots for active doctors' availability patterns.
    Defaults to the next 14 days. An optional event may supply days_ahead.
    """
    try:
        days_ahead = int((event or {}).get("days_ahead", 14))
        if not 1 <= days_ahead <= 90:
            return response(400, {"message": "days_ahead must be between 1 and 90"})
        today = datetime.now(ZoneInfo("UTC")).date()
        end_date = today + timedelta(days=days_ahead)

        conn = dbconn(config())
        created = 0
        skipped_blackout = 0
        skipped_invalid_timezone = 0

        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        ap.doctor_id,
                        ap.day_of_week,
                        ap.start_time,
                        ap.end_time,
                        ap.timezone,
                        ct.consultation_type_id,
                        ct.duration_minutes
                    FROM availability_patterns ap
                    JOIN consultation_types ct
                      ON ct.doctor_id = ap.doctor_id
                    WHERE ap.is_active = TRUE
                      AND ct.is_active = TRUE
                    """
                )
                patterns = cur.fetchall()

                cur.execute(
                    """
                    SELECT doctor_id, blackout_date
                    FROM doctor_blackout_dates
                    WHERE blackout_date BETWEEN %s AND %s
                    """,
                    (today, end_date),
                )
                blackout_rows = cur.fetchall()

                blackouts = {
                    (int(row["doctor_id"]), row["blackout_date"])
                    for row in blackout_rows
                }

                today = datetime.now(ZoneInfo("UTC")).date()
                end_date = today + timedelta(days=days_ahead)

                for pattern in patterns:
                    doctor_id = int(pattern["doctor_id"])
                    weekday = int(pattern["day_of_week"])
                    duration = int(pattern["duration_minutes"])

                    try:
                        timezone = ZoneInfo(pattern.get("timezone") or "UTC")
                    except Exception:
                        skipped_invalid_timezone += 1
                        continue

                    current_date = today
                    while current_date <= end_date:
                        # Python weekday: Monday=0 ... Sunday=6.
                        if current_date.weekday() != weekday:
                            current_date += timedelta(days=1)
                            continue

                        if (doctor_id, current_date) in blackouts:
                            skipped_blackout += 1
                            current_date += timedelta(days=1)
                            continue

                        start_value = pattern["start_time"]
                        end_value = pattern["end_time"]

                        if isinstance(start_value, timedelta):
                            seconds = int(start_value.total_seconds())
                            start_value = time(
                                seconds // 3600,
                                (seconds % 3600) // 60,
                                seconds % 60,
                            )
                        if isinstance(end_value, timedelta):
                            seconds = int(end_value.total_seconds())
                            end_value = time(
                                seconds // 3600,
                                (seconds % 3600) // 60,
                                seconds % 60,
                            )

                        start_local = datetime.combine(current_date, start_value)
                        end_local = datetime.combine(current_date, end_value)

                        while start_local + timedelta(minutes=duration) <= end_local:
                            slot_end_local = start_local + timedelta(minutes=duration)

                            # Store UTC as naive DATETIME values.
                            slot_start_utc = (
                                start_local.replace(tzinfo=timezone)
                                .astimezone(ZoneInfo("UTC"))
                                .replace(tzinfo=None)
                            )
                            slot_end_utc = (
                                slot_end_local.replace(tzinfo=timezone)
                                .astimezone(ZoneInfo("UTC"))
                                .replace(tzinfo=None)
                            )

                            cur.execute(
                                """
                                INSERT IGNORE INTO appointment_slots
                                    (doctor_id, consultation_type_id,
                                     slot_start, slot_end, status)
                                VALUES (%s, %s, %s, %s, 'AVAILABLE')
                                """,
                                (
                                    doctor_id,
                                    int(pattern["consultation_type_id"]),
                                    slot_start_utc,
                                    slot_end_utc,
                                ),
                            )
                            created += cur.rowcount
                            start_local = slot_end_local

                        current_date += timedelta(days=1)

            conn.commit()
        finally:
            conn.close()

        return response(200, {
            "message": "Slot materialisation completed",
            "slots_created": created,
            "blackout_dates_skipped": skipped_blackout,
            "invalid_timezones_skipped": skipped_invalid_timezone,
            "days_ahead": days_ahead,
        })

    except Exception as e:
        print(f"Slot materialisation error: {e!r}")
        return response(500, {"message": "Slot materialisation failed"})
