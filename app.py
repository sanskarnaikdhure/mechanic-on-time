
import os
import secrets
import random
import string
from datetime import datetime
from functools import wraps

from flask import (
    Flask, render_template, request, redirect,
    url_for, session, flash, jsonify, g
)
from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.errors import PyMongoError, ConnectionFailure
import bcrypt


load_dotenv()


app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.getenv("SECRET_KEY", secrets.token_hex(32)),
    MONGO_URI=os.getenv("MONGO_URI", "mongodb://localhost:27017/"),
    MONGO_DB_NAME=os.getenv("MONGO_DB_NAME", "mechanic_on_time")
)


IN_MEMORY_USERS = []
IN_MEMORY_BOOKINGS = []
IN_MEMORY_CONTACTS = []


def _connect_mongo():
    client = MongoClient(
        app.config["MONGO_URI"],
        serverSelectionTimeoutMS=5000,
        connectTimeoutMS=5000,
        socketTimeoutMS=10000
    )
    client.admin.command("ping")
    return client


def _get_db():
    client = getattr(g, "_mongo_client", None)
    db = getattr(g, "_mongo_db", None)
    if client is not None and db is not None:
        try:
            client.admin.command("ping")
            return db
        except Exception:
            client = None
            db = None
    try:
        client = _connect_mongo()
        db = client[app.config["MONGO_DB_NAME"]]
        g._mongo_client = client
        g._mongo_db = db
        return db
    except Exception as err:
        print("[DB] Connection failed:", err)
        return None


@app.before_request
def _ensure_mongo_available():
    db = _get_db()
    g._mongodb_available = db is not None


def get_collection(name):
    db = _get_db()
    if db is None:
        return None
    return db[name]


def insert_document(collection_name, doc, label="record"):
    col = get_collection(collection_name)
    if col is None:
        print(f"[DB] Cannot insert {label}: MongoDB is unreachable")
        flash(
            "Database is currently unavailable. Your "
            + label
            + " was saved temporarily but may be lost. Please try again in a moment.",
            "error"
        )
        in_memory = {
            "users": IN_MEMORY_USERS,
            "bookings": IN_MEMORY_BOOKINGS,
            "contacts": IN_MEMORY_CONTACTS,
        }.get(collection_name)
        if in_memory is not None:
            in_memory.append(doc)
        return False
    try:
        result = col.insert_one(dict(doc))
        print(f"[DB] Inserted {label} into '{collection_name}' _id={result.inserted_id}")
        return True
    except PyMongoError as err:
        print(f"[DB] Insert error on '{collection_name}':", err)
        flash(
            f"Database error while saving {label}. Please try again.",
            "error"
        )
        in_memory = {
            "users": IN_MEMORY_USERS,
            "bookings": IN_MEMORY_BOOKINGS,
            "contacts": IN_MEMORY_CONTACTS,
        }.get(collection_name)
        if in_memory is not None:
            in_memory.append(doc)
        return False


def find_one_user(query):
    col = get_collection("users")
    if col is None:
        for u in IN_MEMORY_USERS:
            match = True
            for k, v in query.items():
                if u.get(k) != v:
                    match = False
                    break
            if match:
                return u
        return None
    try:
        return col.find_one(query)
    except PyMongoError as err:
        print("[DB] find_one_user error:", err)
        flash("Database error while looking up account. Please try again.", "error")
        return None


def find_bookings_for_user(email):
    col = get_collection("bookings")
    if col is None:
        return [b for b in reversed(IN_MEMORY_BOOKINGS) if b.get("email") == email]
    try:
        cursor = col.find({"email": email}).sort("created_at", -1)
        return list(cursor)
    except PyMongoError as err:
        print("[DB] find_bookings_for_user error:", err)
        flash("Database error while loading bookings.", "error")
        return []


def find_single_booking_for_user(email, booking_id):
    col = get_collection("bookings")
    if col is None:
        for b in IN_MEMORY_BOOKINGS:
            if b.get("email") == email and str(b.get("booking_id")) == str(booking_id):
                return b
        return None
    try:
        return col.find_one({"email": email, "booking_id": booking_id})
    except PyMongoError as err:
        print("[DB] find_single_booking_for_user error:", err)
        return None


def update_booking_status(booking_id, email, status):
    col = get_collection("bookings")
    if col is None:
        for b in IN_MEMORY_BOOKINGS:
            if b.get("email") == email and str(b.get("booking_id")) == str(booking_id):
                b["status"] = status
                if "cancelled_at" not in b:
                    b["cancelled_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                return True
        return False
    try:
        result = col.update_one(
            {"email": email, "booking_id": booking_id},
            {"$set": {"status": status,
                      "cancelled_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}}
        )
        return result.modified_count > 0
    except PyMongoError as err:
        print("[DB] update_booking_status error:", err)
        return False


def count_collection(collection_name):
    col = get_collection(collection_name)
    if col is None:
        fallback = {
            "users": len(IN_MEMORY_USERS),
            "bookings": len(IN_MEMORY_BOOKINGS),
            "contacts": len(IN_MEMORY_CONTACTS),
        }.get(collection_name, 0)
        return fallback
    try:
        return col.count_documents({})
    except PyMongoError:
        fallback = {
            "users": len(IN_MEMORY_USERS),
            "bookings": len(IN_MEMORY_BOOKINGS),
            "contacts": len(IN_MEMORY_CONTACTS),
        }.get(collection_name, 0)
        return fallback


def update_user_password(email, new_hashed_password):
    col = get_collection("users")
    if col is None:
        for u in IN_MEMORY_USERS:
            if u.get("email") == email:
                u["password"] = new_hashed_password
                u["password_updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                return True
        return False
    try:
        result = col.update_one(
            {"email": email},
            {"$set": {
                "password": new_hashed_password,
                "password_updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }}
        )
        return result.modified_count > 0
    except PyMongoError as err:
        print("[DB] update_user_password error:", err)
        return False


# =====================================================
# UTILITIES
# =====================================================

def generate_booking_id():
    chars = string.ascii_uppercase + string.digits
    return "MOT" + "".join(random.choices(chars, k=8))


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("user"):
            flash("Please login to access this page.", "error")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function


# =====================================================
# INITIAL DB CHECK (startup banner only)
# =====================================================

with app.app_context():
    test_db = _get_db()
    if test_db is not None:
        print("=" * 60)
        print("  MongoDB connected successfully!")
        print("  Database:", app.config["MONGO_DB_NAME"])
        print("=" * 60)
    else:
        print("=" * 60)
        print("  WARNING: MongoDB could not be reached at startup.")
        print("  URI:", app.config["MONGO_URI"])
        print("  App will retry per request and use in-memory fallback.")
        print("=" * 60)


# =====================================================
# HOME PAGE
# =====================================================

@app.route("/")
def home():
    return render_template("index.html")


# =====================================================
# SERVICES PAGE
# =====================================================

@app.route("/services")
def services():
    return render_template("services.html")


# =====================================================
# BOOKING PAGE
# =====================================================

@app.route("/booking", methods=["GET", "POST"])
def booking():

    if request.method == "POST":

        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()
        email = request.form.get("email", "").strip()
        vehicle = request.form.get("vehicle", "").strip()
        vehicle_number = request.form.get("vehicle_number", "").strip()
        service = request.form.get("service", "").strip()
        location = request.form.get("location", "").strip()
        date = request.form.get("date", "").strip()
        time_slot = request.form.get("time", "").strip()
        problem = request.form.get("problem", "").strip()

        if not all([name, phone, email, vehicle, vehicle_number,
                    service, location, date, time_slot]):
            flash("Please fill in all required fields.", "error")
            return redirect(url_for("booking"))

        booking_id = generate_booking_id()
        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        user_email = session.get("user", {}).get("email", email) if session.get("user") else email

        booking_doc = {
            "booking_id": booking_id,
            "name": name,
            "phone": phone,
            "email": user_email,
            "vehicle": vehicle,
            "vehicle_number": vehicle_number,
            "service": service,
            "location": location,
            "date": date,
            "time": time_slot,
            "problem": problem,
            "status": "Pending",
            "created_at": created_at
        }

        saved = insert_document("bookings", booking_doc, label="booking")

        print("\n")
        print("=" * 50)
        print("          NEW BOOKING")
        print("=" * 50)
        print("Booking ID     :", booking_id)
        print("Name           :", name)
        print("Phone          :", phone)
        print("Email          :", user_email)
        print("Vehicle        :", vehicle)
        print("Vehicle Number :", vehicle_number)
        print("Service        :", service)
        print("Location       :", location)
        print("Date           :", date)
        print("Time           :", time_slot)
        print("Problem        :", problem)
        print("DB Saved       :", "YES" if saved else "NO (fallback)")
        print("=" * 50)
        print("\n")

        session["last_booking"] = booking_doc

        return redirect(url_for("booking_success"))

    return render_template("booking.html")


# =====================================================
# BOOKING SUCCESS PAGE
# =====================================================

@app.route("/booking-success")
def booking_success():
    booking_data = session.pop("last_booking", None)
    return render_template("booking_success.html", booking=booking_data)


# =====================================================
# CONTACT PAGE
# =====================================================

@app.route("/contact", methods=["GET", "POST"])
def contact():

    if request.method == "POST":

        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()
        email = request.form.get("email", "").strip()
        subject = request.form.get("subject", "").strip()
        message = request.form.get("message", "").strip()

        if not all([name, phone, email, subject, message]):
            flash("Please fill in all fields.", "error")
            return redirect(url_for("contact"))

        contact_doc = {
            "name": name,
            "phone": phone,
            "email": email,
            "subject": subject,
            "message": message,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "status": "Unread"
        }

        insert_document("contacts", contact_doc, label="message")

        print("\nNew contact message from:", name, "| subject:", subject)
        print("=" * 40)

        flash("Thank you! Your message has been sent. We'll get back to you soon.", "success")
        return redirect(url_for("contact"))

    return render_template("contact.html")


# =====================================================
# LOGIN PAGE
# =====================================================

@app.route("/login", methods=["GET", "POST"])
def login():

    if session.get("user"):
        return redirect(url_for("dashboard"))

    if request.method == "POST":

        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not email or not password:
            flash("Please enter both email and password.", "error")
            return redirect(url_for("login"))

        user = find_one_user({"email": email})

        if not user:
            print(f"[Auth] Login failed: no user found for email={email}")
            flash("No account found with this email. Please register first.", "error")
            return redirect(url_for("login"))

        if not verify_password(password, user.get("password", "")):
            print(f"[Auth] Login failed: wrong password for email={email}")
            flash("Incorrect password. Please try again.", "error")
            return redirect(url_for("login"))

        session["user"] = {
            "name": user.get("name"),
            "email": user.get("email"),
            "phone": user.get("phone"),
            "logged_in_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

        print("\n[Auth] User logged in:", user.get("name"), "|", user.get("email"))
        print("=" * 40)

        flash(f"Welcome back, {user.get('name')}!", "success")
        return redirect(url_for("dashboard"))

    return render_template("login.html")


# =====================================================
# REGISTER PAGE
# =====================================================

@app.route("/register", methods=["GET", "POST"])
def register():

    if session.get("user"):
        return redirect(url_for("dashboard"))

    if request.method == "POST":

        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not all([name, email, phone, password, confirm_password]):
            flash("Please fill in all fields.", "error")
            return redirect(url_for("register"))

        if password != confirm_password:
            flash("Passwords do not match. Please try again.", "error")
            return redirect(url_for("register"))

        if len(password) < 8:
            flash("Password must be at least 8 characters long.", "error")
            return redirect(url_for("register"))

        existing = find_one_user({"email": email})

        if existing:
            flash("An account with this email already exists. Please login.", "error")
            return redirect(url_for("register"))

        hashed_pw = hash_password(password)

        user_doc = {
            "name": name,
            "email": email,
            "phone": phone,
            "password": hashed_pw,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "role": "customer"
        }

        saved = insert_document("users", user_doc, label="account")

        print("\n")
        print("=" * 40)
        print("       NEW USER REGISTRATION")
        print("=" * 40)
        print("Name     :", name)
        print("Email    :", email)
        print("Phone    :", phone)
        print("DB Saved :", "YES" if saved else "NO (fallback)")
        print("=" * 40)
        print("\n")

        flash("Registration successful! Please login to your account.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")


# =====================================================
# FORGOT PASSWORD PAGE
# =====================================================

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():

    if session.get("user"):
        return redirect(url_for("dashboard"))

    if request.method == "POST":

        email = request.form.get("email", "").strip().lower()

        if not email:
            flash("Please enter your email address.", "error")
            return redirect(url_for("forgot_password"))

        user = find_one_user({"email": email})

        if not user:
            print(f"[Auth] Forgot password: no user found for email={email}")
            flash("No account found with this email. Please register first.", "error")
            return redirect(url_for("forgot_password"))

        reset_token = secrets.token_urlsafe(32)
        session["password_reset_email"] = email
        session["password_reset_token"] = reset_token
        session["password_reset_expiry"] = datetime.now().timestamp() + 1800

        print("\n[Auth] Password reset initiated for:", email)
        print("=" * 40)
        print("Reset Token   :", reset_token)
        print("User Name     :", user.get("name"))
        print("Valid for     : 30 minutes")
        print("=" * 40)
        print()

        flash("Account verified! You can now set a new password.", "success")
        return redirect(url_for("reset_password"))

    return render_template("forgot_password.html")


# =====================================================
# RESET PASSWORD PAGE
# =====================================================

@app.route("/reset-password", methods=["GET", "POST"])
def reset_password():

    if session.get("user"):
        return redirect(url_for("dashboard"))

    email = session.get("password_reset_email")
    expiry = session.get("password_reset_expiry")

    if not email:
        flash("Please start the password reset process first.", "error")
        return redirect(url_for("forgot_password"))

    if expiry and datetime.now().timestamp() > expiry:
        session.pop("password_reset_email", None)
        session.pop("password_reset_token", None)
        session.pop("password_reset_expiry", None)
        flash("Reset session has expired. Please try again.", "error")
        return redirect(url_for("forgot_password"))

    if request.method == "POST":

        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not all([new_password, confirm_password]):
            flash("Please fill in both password fields.", "error")
            return redirect(url_for("reset_password"))

        if new_password != confirm_password:
            flash("Passwords do not match. Please try again.", "error")
            return redirect(url_for("reset_password"))

        if len(new_password) < 8:
            flash("Password must be at least 8 characters long.", "error")
            return redirect(url_for("reset_password"))

        hashed_pw = hash_password(new_password)
        success = update_user_password(email, hashed_pw)

        if success:
            session.pop("password_reset_email", None)
            session.pop("password_reset_token", None)
            session.pop("password_reset_expiry", None)

            print("\n[Auth] Password reset successful for:", email)
            print("=" * 40)

            flash("Password updated successfully! You can now login with your new password.", "success")
            return redirect(url_for("login"))
        else:
            flash("Failed to update password. Please try again.", "error")
            return redirect(url_for("reset_password"))

    return render_template("reset_password.html", email=email)


# =====================================================
# DASHBOARD PAGE
# =====================================================

@app.route("/dashboard")
@login_required
def dashboard():
    user_email = session["user"]["email"]
    user_bookings = find_bookings_for_user(user_email)

    total = len(user_bookings)
    completed = sum(1 for b in user_bookings if b.get("status") == "Completed")
    cancelled = sum(1 for b in user_bookings if b.get("status") == "Cancelled")
    pending = total - completed - cancelled

    return render_template(
        "dashboard.html",
        bookings=user_bookings,
        total_bookings=total,
        completed_bookings=completed,
        pending_bookings=pending,
        cancelled_bookings=cancelled
    )


# =====================================================
# CANCEL BOOKING
# =====================================================

@app.route("/cancel-booking/<booking_id>", methods=["GET", "POST"])
@login_required
def cancel_booking(booking_id):
    user_email = session["user"]["email"]

    booking = find_single_booking_for_user(user_email, booking_id)
    if not booking:
        flash("Booking not found.", "error")
        return redirect(url_for("dashboard"))

    current_status = booking.get("status", "Pending")

    if request.method == "GET":
        if current_status == "Completed":
            flash("Completed bookings cannot be cancelled.", "error")
            return redirect(url_for("dashboard"))

        if current_status == "Cancelled":
            flash("This booking is already cancelled.", "error")
            return redirect(url_for("dashboard"))

        user_nav = ""
        if session.get("user"):
            user_nav = '<a href="/dashboard">Dashboard</a>'
        else:
            user_nav = '<a href="/login" class="login-btn">Login</a>'

        return f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Cancel Booking | Mechanic on Time</title>
            <link rel="stylesheet" href="{url_for('static', filename='css/style.css')}">
        </head>
        <body>
            <header class="navbar">
                <div class="logo">🔧 <span>Mechanic</span> on Time</div>
                <nav>
                    <a href="/">Home</a>
                    <a href="/services">Services</a>
                    <a href="/booking">Book Mechanic</a>
                    <a href="/contact">Contact</a>
                    {user_nav}
                </nav>
            </header>
            <section class="auth-page">
                <div class="auth-container" style="max-width: 600px; text-align: center;">
                    <div style="width: 80px; height: 80px; border-radius: 50%; background: #fef2f2; display: flex; align-items: center; justify-content: center; font-size: 40px; margin: 0 auto 20px;">
                        ❌
                    </div>
                    <h1 style="color: #991b1b; margin-bottom: 10px;">Cancel Booking</h1>
                    <p style="color: #6b7280; margin-bottom: 25px;">Please confirm that you want to cancel this booking. This action cannot be undone.</p>

                    <div style="background: #f8fafc; border: 1px solid #e5e7eb; border-radius: 12px; padding: 22px; text-align: left; margin-bottom: 25px;">
                        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px;">
                            <div>
                                <p style="font-size: 12px; color: #6b7280; font-weight: 600; text-transform: uppercase; letter-spacing: 1px;">Booking ID</p>
                                <p style="color: #111827; font-weight: 700;">#{booking.get('booking_id', booking_id)}</p>
                            </div>
                            <div>
                                <p style="font-size: 12px; color: #6b7280; font-weight: 600; text-transform: uppercase; letter-spacing: 1px;">Service</p>
                                <p style="color: #111827; font-weight: 700;">{booking.get('service', '-')}</p>
                            </div>
                            <div>
                                <p style="font-size: 12px; color: #6b7280; font-weight: 600; text-transform: uppercase; letter-spacing: 1px;">Date</p>
                                <p style="color: #111827;">{booking.get('date', '-')}</p>
                            </div>
                            <div>
                                <p style="font-size: 12px; color: #6b7280; font-weight: 600; text-transform: uppercase; letter-spacing: 1px;">Time</p>
                                <p style="color: #111827;">{booking.get('time', '-')}</p>
                            </div>
                            <div>
                                <p style="font-size: 12px; color: #6b7280; font-weight: 600; text-transform: uppercase; letter-spacing: 1px;">Vehicle</p>
                                <p style="color: #111827;">{booking.get('vehicle', '-')}</p>
                            </div>
                            <div>
                                <p style="font-size: 12px; color: #6b7280; font-weight: 600; text-transform: uppercase; letter-spacing: 1px;">Vehicle No.</p>
                                <p style="color: #111827;">{booking.get('vehicle_number', '-')}</p>
                            </div>
                        </div>
                    </div>

                    <form method="POST" action="/cancel-booking/{booking_id}" style="display: flex; gap: 12px; flex-wrap: wrap;">
                        <button type="submit" style="flex: 1; padding: 15px; border: 1px solid #fecaca; border-radius: 8px; background: #dc2626; color: #fff; font-weight: 700; cursor: pointer; font-size: 15px;">
                            ❌ Confirm Cancellation
                        </button>
                        <a href="/dashboard" style="flex: 1; padding: 15px; border-radius: 8px; background: #374151; color: #fff; font-weight: 700; text-decoration: none; font-size: 15px; display: inline-flex; align-items: center; justify-content: center;">
                            ← Go Back
                        </a>
                    </form>
                </div>
            </section>
        </body>
        </html>
        """

    if current_status == "Completed":
        flash("Completed bookings cannot be cancelled.", "error")
        return redirect(url_for("dashboard"))

    if current_status == "Cancelled":
        flash("This booking is already cancelled.", "error")
        return redirect(url_for("dashboard"))

    success = update_booking_status(booking_id, user_email, "Cancelled")

    if success:
        flash(f"Booking {booking_id} has been cancelled successfully.", "success")
        print(f"[Booking] Cancelled booking {booking_id} for {user_email}")
    else:
        flash("Failed to cancel booking. Please try again.", "error")

    return redirect(url_for("dashboard"))


# =====================================================
# COMPLETE BOOKING
# =====================================================

@app.route("/complete-booking/<booking_id>", methods=["GET", "POST"])
@login_required
def complete_booking(booking_id):
    user_email = session["user"]["email"]

    booking = find_single_booking_for_user(user_email, booking_id)
    if not booking:
        flash("Booking not found.", "error")
        return redirect(url_for("dashboard"))

    current_status = booking.get("status", "Pending")

    if request.method == "GET":
        if current_status == "Cancelled":
            flash("Cancelled bookings cannot be marked as completed.", "error")
            return redirect(url_for("dashboard"))

        if current_status == "Completed":
            flash("This booking is already marked as completed.", "error")
            return redirect(url_for("dashboard"))

        user_nav = ""
        if session.get("user"):
            user_nav = '<a href="/dashboard">Dashboard</a>'
        else:
            user_nav = '<a href="/login" class="login-btn">Login</a>'

        return f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Mark Booking Completed | Mechanic on Time</title>
            <link rel="stylesheet" href="{url_for('static', filename='css/style.css')}">
        </head>
        <body>
            <header class="navbar">
                <div class="logo">🔧 <span>Mechanic</span> on Time</div>
                <nav>
                    <a href="/">Home</a>
                    <a href="/services">Services</a>
                    <a href="/booking">Book Mechanic</a>
                    <a href="/contact">Contact</a>
                    {user_nav}
                </nav>
            </header>
            <section class="auth-page">
                <div class="auth-container" style="max-width: 600px; text-align: center;">
                    <div style="width: 80px; height: 80px; border-radius: 50%; background: #dcfce7; display: flex; align-items: center; justify-content: center; font-size: 40px; margin: 0 auto 20px;">
                        ✅
                    </div>
                    <h1 style="color: #166534; margin-bottom: 10px;">Mark Booking as Completed</h1>
                    <p style="color: #6b7280; margin-bottom: 25px;">Please confirm that the service for this booking has been fully completed.</p>

                    <div style="background: #f8fafc; border: 1px solid #e5e7eb; border-radius: 12px; padding: 22px; text-align: left; margin-bottom: 25px;">
                        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px;">
                            <div>
                                <p style="font-size: 12px; color: #6b7280; font-weight: 600; text-transform: uppercase; letter-spacing: 1px;">Booking ID</p>
                                <p style="color: #111827; font-weight: 700;">#{booking.get('booking_id', booking_id)}</p>
                            </div>
                            <div>
                                <p style="font-size: 12px; color: #6b7280; font-weight: 600; text-transform: uppercase; letter-spacing: 1px;">Service</p>
                                <p style="color: #111827; font-weight: 700;">{booking.get('service', '-')}</p>
                            </div>
                            <div>
                                <p style="font-size: 12px; color: #6b7280; font-weight: 600; text-transform: uppercase; letter-spacing: 1px;">Date</p>
                                <p style="color: #111827;">{booking.get('date', '-')}</p>
                            </div>
                            <div>
                                <p style="font-size: 12px; color: #6b7280; font-weight: 600; text-transform: uppercase; letter-spacing: 1px;">Time</p>
                                <p style="color: #111827;">{booking.get('time', '-')}</p>
                            </div>
                            <div>
                                <p style="font-size: 12px; color: #6b7280; font-weight: 600; text-transform: uppercase; letter-spacing: 1px;">Vehicle</p>
                                <p style="color: #111827;">{booking.get('vehicle', '-')}</p>
                            </div>
                            <div>
                                <p style="font-size: 12px; color: #6b7280; font-weight: 600; text-transform: uppercase; letter-spacing: 1px;">Vehicle No.</p>
                                <p style="color: #111827;">{booking.get('vehicle_number', '-')}</p>
                            </div>
                        </div>
                    </div>

                    <form method="POST" action="/complete-booking/{booking_id}" style="display: flex; gap: 12px; flex-wrap: wrap;">
                        <button type="submit" style="flex: 1; padding: 15px; border: 1px solid #86efac; border-radius: 8px; background: #22c55e; color: #fff; font-weight: 700; cursor: pointer; font-size: 15px;">
                            ✅ Mark as Completed
                        </button>
                        <a href="/dashboard" style="flex: 1; padding: 15px; border-radius: 8px; background: #374151; color: #fff; font-weight: 700; text-decoration: none; font-size: 15px; display: inline-flex; align-items: center; justify-content: center;">
                            ← Go Back
                        </a>
                    </form>
                </div>
            </section>
        </body>
        </html>
        """

    if current_status == "Cancelled":
        flash("Cancelled bookings cannot be marked as completed.", "error")
        return redirect(url_for("dashboard"))

    if current_status == "Completed":
        flash("This booking is already marked as completed.", "error")
        return redirect(url_for("dashboard"))

    col = get_collection("bookings")
    if col is None:
        for b in IN_MEMORY_BOOKINGS:
            if b.get("email") == user_email and str(b.get("booking_id")) == str(booking_id):
                b["status"] = "Completed"
                if "completed_at" not in b:
                    b["completed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                success = True
                break
        else:
            success = False
    else:
        try:
            result = col.update_one(
                {"email": user_email, "booking_id": booking_id},
                {"$set": {"status": "Completed",
                          "completed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}}
            )
            success = result.modified_count > 0
        except PyMongoError as err:
            print("[DB] complete_booking error:", err)
            success = False

    if success:
        flash(f"Booking {booking_id} has been marked as completed! 🎉", "success")
        print(f"[Booking] Completed booking {booking_id} for {user_email}")
    else:
        flash("Failed to mark booking as completed. Please try again.", "error")

    return redirect(url_for("dashboard"))


# =====================================================
# LOGOUT
# =====================================================

@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out successfully.", "success")
    return redirect(url_for("home"))


# =====================================================
# JSON API: Check MongoDB connection status
# =====================================================

@app.route("/api/status")
def api_status():
    db = _get_db()
    mongo_ok = db is not None
    return jsonify({
        "status": "ok",
        "mongodb_connected": mongo_ok,
        "database": app.config["MONGO_DB_NAME"] if mongo_ok else None,
        "total_users": count_collection("users"),
        "total_bookings": count_collection("bookings"),
        "total_messages": count_collection("contacts"),
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })


# =====================================================
# ERROR PAGE - 404
# =====================================================

@app.errorhandler(404)
def page_not_found(error):
    return """
    <div style="min-height:100vh; display:flex; align-items:center; justify-content:center;
         background:#f8fafc; font-family:Arial,sans-serif; padding:20px;">
        <div style="text-align:center; max-width:500px;">
            <div style="font-size:100px; margin-bottom:20px;">🔧</div>
            <h1 style="font-size:48px; color:#111827; margin-bottom:12px;">404</h1>
            <h2 style="font-size:24px; color:#374151; margin-bottom:15px;">Page Not Found</h2>
            <p style="color:#6b7280; margin-bottom:30px; line-height:1.7;">
                The page you are looking for does not exist or has been moved.
            </p>
            <a href="/" style="display:inline-block; padding:14px 28px; background:#f97316;
               color:#ffffff; text-decoration:none; border-radius:8px; font-weight:700;">
                🏠 Go to Home
            </a>
        </div>
    </div>
    """, 404


# =====================================================
# RUN FLASK APPLICATION
# =====================================================

if __name__ == "__main__":
    booking_rules = sorted(
        str(r) for r in app.url_map.iter_rules() if 'booking' in str(r)
    )
    print("\n=== Registered Booking Routes ===")
    for r in booking_rules:
        print(f"  ✓ {r}")
    print("=================================\n")

    app.run(
        host="127.0.0.1",
        port=5000,
        debug=True,
        use_reloader=False
    )
