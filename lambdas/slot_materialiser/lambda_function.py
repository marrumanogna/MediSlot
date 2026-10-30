
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from common import config, dbconn, response


UTC = ZoneInfo("UTC")


def as_time(value):
    """Convert MySQL TIME values to Python time objects."""
    if isinstance(value, timedelta):
        seconds = int(value.total_seconds())
        return time(
            (seconds // 3600) % 24,
            (seconds % 3600) // 60,
            seconds % 60,
        )
    return value


def localize_slot(local_dt, timezone):
    """
    Convert a local wall time to naive UTC for MySQL DATETIME.

    Reject nonexistent local times during spring DST transitions.
    For ambiguous times during autumn DST transitions, consistently
    choose the first occurrence (fold=0).
    """
    candidate = local_dt.replace(tzinfo=timezone, fold=0)
    utc_dt = candidate.astimezone(UTC)

    # Round-trip detects local times that do not exist.
    round_trip = utc_dt.astimezone(timezone).replace(tzinfo=None)
    if round_trip != local_dt:
        return None

    return utc_dt.replace(tzinfo=None)


def handler(event, context):
    """Generate appointment slots for the next 30 days by default."""
    try:
        days_ahead = int((event or {}).get("days_ahead", 30))
        if not 1 <= days_ahead <= 90:
            return response(
                400,
                {"message": "days_ahead must be between 1 and 90"},
            )

        # Fetch a broad range of blackout dates to cover local dates
        # that may differ from UTC dates near midnight.
        utc_today = datetime.now(UTC).date()
        utc_end_date = utc_today + timedelta(days=days_ahead)

        conn = dbconn(config())
        created = 0
        skipped_blackout = 0
        skipped_invalid_timezone = 0
        skipped_dst_time = 0

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
                    (
                        utc_today - timedelta(days=1),
                        utc_end_date + timedelta(days=1),
                    ),
                )
                blackout_rows = cur.fetchall()

                blackouts = {
                    (int(row["doctor_id"]), row["blackout_date"])
                    for row in blackout_rows
                }

                now_utc = datetime.now(UTC).replace(tzinfo=None)

                for pattern in patterns:
                    doctor_id = int(pattern["doctor_id"])
                    weekday = int(pattern["day_of_week"])
                    duration = int(pattern["duration_minutes"])

                    if duration <= 0:
                        continue

                    try:
                        timezone = ZoneInfo(pattern.get("timezone") or "UTC")
                    except (ZoneInfoNotFoundError, ValueError, TypeError):
                        skipped_invalid_timezone += 1
                        continue

                    # Use the doctor's local calendar for weekly patterns.
                    current_date = datetime.now(timezone).date()
                    local_end_date = current_date + timedelta(days=days_ahead)

                    start_value = as_time(pattern["start_time"])
                    end_value = as_time(pattern["end_time"])

                    if start_value >= end_value:
                        continue

                    while current_date <= local_end_date:
                        if current_date.weekday() != weekday:
                            current_date += timedelta(days=1)
                            continue

                        if (doctor_id, current_date) in blackouts:
                            skipped_blackout += 1
                            current_date += timedelta(days=1)
                            continue

                        start_local = datetime.combine(current_date, start_value)
                        end_local = datetime.combine(current_date, end_value)

                        while (
                            start_local + timedelta(minutes=duration)
                            <= end_local
                        ):
                            slot_end_local = start_local + timedelta(
                                minutes=duration
                            )

                            slot_start_utc = localize_slot(start_local, timezone)
                            slot_end_utc = localize_slot(slot_end_local, timezone)

                            if (
                                slot_start_utc is None
                                or slot_end_utc is None
                                or slot_end_utc <= slot_start_utc
                            ):
                                skipped_dst_time += 1
                                start_local = slot_end_local
                                continue

                            # Never create slots that have already started.
                            if slot_start_utc >= now_utc:
                                cur.execute(
                                    """
                                    INSERT IGNORE INTO appointment_slots
                                        (
                                            doctor_id,
                                            consultation_type_id,
                                            slot_start,
                                            slot_end,
                                            status
                                        )
                                    VALUES (%s, %s, %s, %s, 'AVAILABLE')
                                    """,
                                    (
                                        doctor_id,
                                        int(pattern["consultation_type_id"]),
                                        slot_start_utc,
                                        slot_end_utc,
                                    ),
                                )

                                # INSERT IGNORE reports zero for a duplicate
                                # when the database unique key is present.
                                created += max(cur.rowcount, 0)

                            start_local = slot_end_local

                        current_date += timedelta(days=1)

            conn.commit()
        finally:
            conn.close()

        return response(
            200,
            {
                "message": "Slot materialisation completed",
                "slots_created": created,
                "blackout_dates_skipped": skipped_blackout,
                "invalid_timezones_skipped": skipped_invalid_timezone,
                "dst_times_skipped": skipped_dst_time,
                "days_ahead": days_ahead,
            },
        )

    except Exception as e:
        print(f"Slot materialisation error: {e!r}")
        return response(
            500,
            {"message": "Slot materialisation failed"},
        )
