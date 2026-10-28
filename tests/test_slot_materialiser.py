import importlib.util
import os
import sys
from datetime import date, timedelta, time
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lambdas"))
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("AWS_EC2_METADATA_DISABLED", "true")


def load_lambda():
    path = ROOT / "lambdas" / "slot_materialiser" / "lambda_function.py"
    spec = importlib.util.spec_from_file_location("slot_materialiser", path)
    module = importlib.util.module_from_spec(spec)
    with patch("boto3.client"), patch("boto3.resource"):
        spec.loader.exec_module(module)
    return module


def test_invalid_days_ahead():
    module = load_lambda()
    module.response = lambda status, data: {"statusCode": status, "body": data}

    result = module.handler({"days_ahead": 0}, None)

    assert result["statusCode"] == 400


def test_materialises_slots_and_skips_blackout():
    module = load_lambda()
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    module.config = MagicMock(return_value={})
    module.dbconn = MagicMock(return_value=conn)
    module.response = lambda status, data: {"statusCode": status, "body": data}

    today = date.today()
    weekday = today.weekday()
    pattern = {
        "doctor_id": 12,
        "day_of_week": weekday,
        "start_time": time(9, 0),
        "end_time": time(10, 0),
        "timezone": "UTC",
        "consultation_type_id": 5,
        "duration_minutes": 30,
    }

    cursor.fetchall.side_effect = [
        [pattern],
        [{"doctor_id": 12, "blackout_date": today}],
    ]

    with patch("datetime.datetime") as mock_datetime:
        mock_datetime.now.return_value.date.return_value = today
        result = module.handler({"days_ahead": 1}, None)

    assert result["statusCode"] == 200
    assert result["body"]["blackout_dates_skipped"] >= 1
    conn.commit.assert_called_once()
    conn.close.assert_called_once()
