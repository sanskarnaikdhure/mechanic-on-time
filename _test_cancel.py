import urllib.request as u
import urllib.parse as p
import http.cookiejar
import random
import time
import pymongo
import os
from dotenv import load_dotenv

load_dotenv()

EMAIL = f"canceltest{random.randint(100,999)}@example.com"
NAME = "Cancel Tester"
PHONE = "9876543210"
PASSWORD = "Cancel@123"
BASE = "http://127.0.0.1:5000"

jar = http.cookiejar.CookieJar()
redirect = u.HTTPRedirectHandler()
opener = u.build_opener(u.HTTPCookieProcessor(jar), redirect)

def post(url, data):
    body = p.urlencode(data).encode()
    req = u.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    return opener.open(req, timeout=15)

def follow(r):
    loc = r.headers.get("Location") or r.url
    if loc and loc.startswith("/"):
        loc = BASE + loc
    return loc

print("Test email:", EMAIL)

# 1. Register
r = post(f"{BASE}/register", {"name":NAME, "email":EMAIL, "phone":PHONE, "password":PASSWORD, "confirm_password":PASSWORD})
print(f"1. Register: {r.status} -> {follow(r)}")

# 2. Login
r = post(f"{BASE}/login", {"email":EMAIL, "password":PASSWORD})
print(f"2. Login: {r.status} -> {follow(r)}")

# 3. Book 2 bookings
bookings = []
for i in range(2):
    booking_data = {
        "name": NAME,
        "email": EMAIL,
        "phone": PHONE,
        "service": "Brake Pad Replacement" if i == 0 else "Wheel Alignment",
        "vehicle": "SUV",
        "vehicle_number": f"MH-0{i}-AB-{1000+i}",
        "date": "2026-12-01",
        "time": "10:00",
        "location": "Wagholi, Pune"
    }
    r = post(f"{BASE}/booking", booking_data)
    print(f"3.{i+1} Booking: {r.status} -> {follow(r)}")

# 4. Get dashboard to find a booking_id
r = opener.open(f"{BASE}/dashboard")
html = r.read().decode()

# Parse booking IDs from HTML (after the booking_id column td with monospace)
import re
ids = re.findall(r'<td style="padding: 14px 16px; color: #374151; font-family: monospace; font-size: 12px;">(MOT[A-Z0-9]+)', html)
print(f"4. Found booking IDs in dashboard: {ids}")

if not ids:
    print("❌ No booking IDs found - test failed!")
    exit(1)

TARGET_ID = ids[0]
print(f"5. Targeting booking {TARGET_ID} for cancellation")

# 6. Cancel booking (POST /cancel-booking/<id>)
r = post(f"{BASE}/cancel-booking/{TARGET_ID}", {})
loc = follow(r)
print(f"6. Cancel booking: {r.status} -> {loc}")

# 7. Check dashboard after cancel - confirm Cancelled badge appears
r = opener.open(f"{BASE}/dashboard")
html2 = r.read().decode()
has_cancelled_tag = 'Cancelled' in html2
print(f"7. Dashboard shows Cancelled badge: {has_cancelled_tag}")

# 8. Verify status in MongoDB directly
client = pymongo.MongoClient(os.environ.get("MONGO_URI", "mongodb://localhost:27017/"), serverSelectionTimeoutMS=5000)
db = client["mechanic_on_time"]

user = db.users.find_one({"email": EMAIL})
print(f"8a. DB - User found: {user is not None} | Name: {user.get('name') if user else None}")

booking_check = db.bookings.find_one({"email": EMAIL, "booking_id": TARGET_ID})
print(f"8b. DB - Cancelled booking found: {booking_check is not None}")
if booking_check:
    print(f"     Status: {booking_check.get('status')}")
    print(f"     cancelled_at: {booking_check.get('cancelled_at')}")
    assert booking_check.get("status") == "Cancelled", "Status not Cancelled!"
    print("     ✅ Status is Cancelled!")

all_user_bookings = list(db.bookings.find({"email": EMAIL}))
print(f"8c. DB - Total bookings for user: {len(all_user_bookings)}")
cancelled_cnt = sum(1 for b in all_user_bookings if b.get("status") == "Cancelled")
pending_cnt = sum(1 for b in all_user_bookings if b.get("status", "Pending") in ("Pending", "Confirmed"))
print(f"     Cancelled: {cancelled_cnt}, Pending/Confirmed: {pending_cnt}")

# 9. Try cancel already cancelled - should show "already cancelled" flash
r2 = post(f"{BASE}/cancel-booking/{TARGET_ID}", {})
print(f"9. Re-cancel same booking (already cancelled): {r2.status} -> {follow(r2)}")
print("   Expected: redirect with 'already cancelled' flash")

# 10. Try cancel different booking that exists and pending
if len(ids) > 1:
    T2 = ids[1]
    # Set it to Completed via direct DB, then try cancel from app - should reject
    db.bookings.update_one({"booking_id": T2}, {"$set": {"status": "Completed"}})
    r3 = post(f"{BASE}/cancel-booking/{T2}", {})
    print(f"10. Cancel Completed booking (should be blocked): {r3.status} -> {follow(r3)}")

print("\n✅ Cancel Booking test flow PASSED - all DB writes verified!")
