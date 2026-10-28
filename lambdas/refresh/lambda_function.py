# IMPORTS
import time, secrets, jwt
from common import config, body, response, emit, correlation, auth_table, token_hash


def handler(event, context):

    cid = correlation(event)

    try:
        # READ REFRESH TOKEN FROM REQUEST BODY
        data = body(event)
        raw = data.get("refreshToken") if isinstance(data, dict) else None

        #IS PROVIDED
        if not isinstance(raw, str) or not raw:
            return response(400, {
                "message": "refreshToken is required",
                "correlationId": cid
            })

        # LOAD CONFIGURATION AND CREATE REFRESH TOKEN LOOKUP KEY
        c = config()
        key = "REFRESH#" + token_hash(raw)

        # GET DYNAMODB AUTH TOKENS TABLE
        t = auth_table()

        # FIND REFRESH TOKEN RECORD IN DYNAMODB
        old = t.get_item(
            Key={
                "token_key": key,
                "token_type": "REFRESH"
            }
        ).get("Item")
        now = int(time.time())

        # VALIDATE TOKEN EXISTS, IS ACTIVE AND HAS NOT EXPIRED
        if (
            not old
            or old.get("status") != "ACTIVE"
            or int(old.get("expires_at", 0)) <= now
        ):
            return response(401, {
                "message": "Invalid or revoked refresh token",
                "correlationId": cid
            })

        # REVOKE OLD REFRESH TOKEN
        # CONDITIONAL UPDATE PREVENTS CONCURRENT REUSE
        t.update_item(
            Key={
                "token_key": key,
                "token_type": "REFRESH"
            },
            UpdateExpression="SET #s=:revoked",
            ConditionExpression="#s=:active",
            ExpressionAttributeNames={
                "#s": "status"
            },
            ExpressionAttributeValues={
                ":revoked": "REVOKED",
                ":active": "ACTIVE"
            }
        )

        # GET ACCESS TOKEN LIFETIME FROM SSM
        minutes = int(
            __import__("common").get_param(
                f"{c['prefix']}/auth/access-token-minutes"
            )
        )

        # GENERATE A NEW UNIQUE JWT ID (JTI)
        jti = __import__("uuid").uuid4().hex

        # CREATE NEW ACCESS TOKEN
        access = jwt.encode(
            {
                "sub": old["user_id"],
                "userId": old["user_id"],
                "role": old["role"],
                "iss": "medislot",
                "aud": "medislot-api",
                "iat": now,
                "exp": now + minutes * 60,
                "jti": jti
            },
            c["jwt"],
            algorithm="HS256"
        )

        # GENERATE A NEW REFRESH TOKEN
        newraw = secrets.token_urlsafe(48)

        # GET REFRESH TOKEN LIFETIME FROM SSM
        days = int(
            __import__("common").get_param(
                f"{c['prefix']}/auth/refresh-token-days"
            )
        )

        # STORE NEW REFRESH TOKEN HASH IN DYNAMODB
        t.put_item(
            Item={
                "token_key": "REFRESH#" + token_hash(newraw),
                "token_type": "REFRESH",
                "user_id": old["user_id"],
                "role": old["role"],
                "created_at": now,
                "expires_at": now + days * 86400,
                "status": "ACTIVE"
            }
        )

        # RETURN NEW ACCESS TOKEN AND REFRESH TOKEN
        return response(200, {
            "accessToken": access,
            "tokenType": "Bearer",
            "expiresIn": minutes * 60,
            "refreshToken": newraw
        })

    # HANDLE ERRORS
    except Exception:
        emit("error", "refresh_failed", cid)
        return response(401, {
            "message": "Invalid or revoked refresh token",
            "correlationId": cid
        })