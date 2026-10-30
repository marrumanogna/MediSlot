import os
import requests

from flask import (
    Flask, render_template, request,
    redirect, url_for, session, flash
)
from flask_session import Session
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

app.config["SECRET_KEY"] = os.environ["FLASK_SECRET_KEY"]
app.config["SESSION_TYPE"] = "filesystem"
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_USE_SIGNER"] = True
app.config["SESSION_FILE_DIR"] = os.path.join(
    os.path.dirname(__file__), "flask_session"
)

Session(app)

API_BASE_URL = os.environ["API_BASE_URL"].rstrip("/")


def doctor_required():
    return (
        "access_token" in session
        and session.get("role") == "DOCTOR"
    )


@app.route("/")
def home():
    if doctor_required():
        return redirect(url_for("doctor_dashboard"))

    return redirect(url_for("login"))


@app.route("/doctor/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        try:
            api_response = requests.post(
                f"{API_BASE_URL}/auth/login",
                json={
                    "email": email,
                    "password": password
                },
                timeout=15
            )

            result = api_response.json()

            if api_response.status_code != 200:
                flash(result.get("message", "Login failed"))
                return render_template("login.html")

            if result.get("role") != "DOCTOR":
                flash("This portal is only for doctors.")
                return render_template("login.html")

            session.clear()

            session["access_token"] = result["accessToken"]
            session["refresh_token"] = result["refreshToken"]
            session["user_id"] = result["userId"]
            session["role"] = result["role"]

            return redirect(url_for("doctor_dashboard"))

        except requests.RequestException:
            flash("Unable to connect to MediSlot API.")
            return render_template("login.html")

    return render_template("login.html")


@app.route("/doctor/dashboard")
def doctor_dashboard():

    if not doctor_required():
        session.clear()
        return redirect(url_for("login"))

    return render_template("doctor_dashboard.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
