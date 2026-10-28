# IMPORTS
import os, time, jwt
from common import get_param, auth_table, emit


def handler(event, context):

    # GET API METHOD ARN AND AUTHORIZATION TOKEN
    method_arn = event.get("methodArn", "*")
    token = (event.get("authorizationToken") or "").strip()
    cid = (event.get("headers") or {}).get("x-correlation-id")

    # REMOVE BEARER PREFIX FROM TOKEN
    if token.lower().startswith("bearer "):
        token = token[7:].strip()

    try:

        # CHECK IF TOKEN IS MISSING
        if not token:
            raise ValueError("missing")

        # GET ENVIRONMENT AND JWT SECRET FROM SSM
        env = os.environ.get("ENVIRONMENT", "dev")
        signing_secret = get_param(
            f"/medislot/{env}/auth/jwt-secret", True
        )

        # VALIDATE JWT SIGNATURE, ISSUER, AUDIENCE AND REQUIRED CLAIMS
        claims = jwt.decode(
            token,
            signing_secret,
            algorithms=["HS256"],
            issuer="medislot",
            audience="medislot-api",
            options={"require": ["exp", "iat", "sub", "jti", "role"]}
        )

        # VALIDATE USER ROLE
        if claims["role"] not in ("PATIENT", "DOCTOR"):
            raise ValueError("role")

        # IDENTIFY THE REQUESTED API ROUTE
        arn_parts = method_arn.split("/")
        route = "/".join(arn_parts[2:]) if len(arn_parts) > 2 else ""

        # CHECK WHETHER ROUTE REQUIRES PATIENT OR DOCTOR ROLE
        expected = "DOCTOR" if "/doctor/" in ("/" + route + "/") else (
            "PATIENT" if "/patient/" in ("/" + route + "/") else None
        )

        # REJECT USER IF ROLE DOES NOT MATCH THE ROUTE
        if expected and claims["role"] != expected:
            raise PermissionError("wrong_role")

        # CHECK TOKEN EXPIRATION TIME
        now = int(time.time())
        if int(claims["exp"]) <= now:
            raise ValueError("expired")

        # CREATE DENYLIST LOOKUP KEY USING JWT ID (JTI)
        key = "JTI#" + str(claims["jti"])

        # CHECK DYNAMODB FOR A REVOKED TOKEN
        item = auth_table().get_item(
            Key={"token_key": key, "token_type": "DENYLIST"}
        ).get("Item")

        # REJECT TOKEN IF AN ACTIVE DENYLIST ENTRY EXISTS
        if item and int(item.get("expires_at", 0)) > now:
            raise ValueError("revoked")

        # RETURN ALLOW POLICY TO API GATEWAY
        # PASS USER ID, ROLE AND JTI TO THE BACKEND LAMBDA
        return {
            "principalId": str(claims["sub"]),
            "policyDocument": {
                "Version": "2012-10-17",
                "Statement": [{
                    "Action": "execute-api:Invoke",
                    "Effect": "Allow",
                    "Resource": method_arn
                }]
            },
            "context": {
                "userId": str(claims["sub"]),
                "role": claims["role"],
                "jti": str(claims["jti"])
            }
        }

    # HANDLE WRONG ROLE
    except PermissionError:
        emit("warning", "authorization_wrong_role", cid)
        return {
            "principalId": "forbidden",
            "policyDocument": {
                "Version": "2012-10-17",
                "Statement": [{
                    "Action": "execute-api:Invoke",
                    "Effect": "Deny",
                    "Resource": method_arn
                }]
            }
        }

    # HANDLE OTHER AUTHORIZATION FAILURES
    except Exception:
        emit("warning", "authorization_rejected", cid)
        raise Exception("Unauthorized")