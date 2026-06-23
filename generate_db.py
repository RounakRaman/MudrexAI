"""
Generates a deliberately messy SQLite database simulating a crypto trading
platform's raw events schema (modeled on what Mudrex's task description implies).

Mess injected on purpose, because "clean up our events schema" is literally
task #1 in the internship scope:
- Inconsistent event_type casing/naming ("ORDER_PLACED" vs "order_placed" vs "OrderPlaced")
- Timestamps in mixed formats (some ISO, some with different separators)
- Nulls scattered in non-critical columns
- A legacy duplicate-ish column (raw_payload) that should arguably be normalized out
- Duplicate event rows (same event logged twice, a common real-world data issue)
"""

import sqlite3
import random
from datetime import datetime, timedelta

random.seed(42)

DB_PATH = "/home/claude/mudrex-prep/mudrex_events.db"

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

cur.executescript("""
DROP TABLE IF EXISTS users;
DROP TABLE IF EXISTS raw_events;
DROP TABLE IF EXISTS orders;

CREATE TABLE users (
    user_id INTEGER PRIMARY KEY,
    signup_ts TEXT,
    country TEXT,
    plan_tier TEXT,
    kyc_status TEXT
);

CREATE TABLE orders (
    order_id INTEGER PRIMARY KEY,
    user_id INTEGER,
    asset TEXT,
    side TEXT,
    qty REAL,
    price REAL,
    status TEXT,
    created_ts TEXT,
    updated_ts TEXT
);

-- This is the messy one: raw event log, inconsistent naming, mixed timestamp
-- formats, occasional nulls, occasional duplicate rows. This is what
-- "cleaning up our events schema" actually means in practice.
CREATE TABLE raw_events (
    event_id INTEGER PRIMARY KEY,
    user_id INTEGER,
    event_type TEXT,
    event_ts TEXT,
    order_id INTEGER,
    raw_payload TEXT
);
""")

assets = ["BTC", "ETH", "SOL", "USDT", "XRP"]
countries = ["IN", "US", "SG", "AE", "GB"]
tiers = ["free", "pro", "pro", "free", "elite"]
kyc = ["verified", "verified", "pending", "verified", "rejected"]

# ---- Users ----
base_date = datetime(2025, 11, 1)
users = []
for uid in range(1, 201):
    signup = base_date + timedelta(days=random.randint(0, 200), hours=random.randint(0, 23))
    # inject some messy timestamp formatting on purpose
    if uid % 7 == 0:
        ts_str = signup.strftime("%d/%m/%Y %H:%M")
    else:
        ts_str = signup.strftime("%Y-%m-%dT%H:%M:%S")
    country = random.choice(countries)
    tier = random.choice(tiers)
    k = random.choice(kyc) if uid % 11 != 0 else None  # some nulls
    users.append((uid, ts_str, country, tier, k))

cur.executemany("INSERT INTO users VALUES (?,?,?,?,?)", users)

# ---- Orders ----
order_id = 1
orders = []
order_lookup = {}
for uid in range(1, 201):
    n_orders = random.randint(0, 12)
    last_ts = None
    for _ in range(n_orders):
        asset = random.choice(assets)
        side = random.choice(["buy", "sell"])
        qty = round(random.uniform(0.001, 5), 4)
        price = round(random.uniform(20, 65000), 2)
        status = random.choices(
            ["filled", "filled", "filled", "cancelled", "pending", "failed"],
            weights=[5, 5, 5, 2, 1, 1],
        )[0]
        created = base_date + timedelta(days=random.randint(0, 220), hours=random.randint(0, 23), minutes=random.randint(0, 59))
        updated = created + timedelta(minutes=random.randint(0, 180))
        orders.append((order_id, uid, asset, side, qty, price, status,
                        created.strftime("%Y-%m-%dT%H:%M:%S"),
                        updated.strftime("%Y-%m-%dT%H:%M:%S")))
        order_lookup[order_id] = (uid, created, status)
        order_id += 1

cur.executemany("INSERT INTO orders VALUES (?,?,?,?,?,?,?,?,?)", orders)

# ---- Raw events (the messy table) ----
event_type_variants = {
    "order_placed": ["order_placed", "ORDER_PLACED", "OrderPlaced"],
    "order_filled": ["order_filled", "ORDER_FILLED", "OrderFilled"],
    "order_cancelled": ["order_cancelled", "ORDER_CANCELLED", "OrderCancelled"],
    "login": ["login", "LOGIN", "user_login"],
    "deposit": ["deposit", "DEPOSIT", "FundsDeposited"],
    "kyc_submitted": ["kyc_submitted", "KYC_SUBMITTED"],
}

events = []
eid = 1
for oid, (uid, created, status) in order_lookup.items():
    # order_placed event
    variant = random.choice(event_type_variants["order_placed"])
    ts = created
    ts_str = ts.strftime("%Y-%m-%dT%H:%M:%S") if eid % 5 != 0 else ts.strftime("%d-%m-%Y %H:%M:%S")
    events.append((eid, uid, variant, ts_str, oid, f'{{"source":"web","status":"{status}"}}'))
    eid += 1

    # sometimes duplicate the placed event (real-world logging bug)
    if random.random() < 0.05:
        events.append((eid, uid, variant, ts_str, oid, f'{{"source":"web","status":"{status}"}}'))
        eid += 1

    if status == "filled":
        key = "order_filled"
        variant2 = random.choice(event_type_variants[key])
        ts2 = created + timedelta(minutes=random.randint(1, 30))
        ts2_str = ts2.strftime("%Y-%m-%dT%H:%M:%S")
        events.append((eid, uid, variant2, ts2_str, oid, '{"source":"matching_engine"}'))
        eid += 1
    elif status == "cancelled":
        variant2 = random.choice(event_type_variants["order_cancelled"])
        ts2 = created + timedelta(minutes=random.randint(1, 60))
        events.append((eid, uid, variant2, ts2.strftime("%Y-%m-%dT%H:%M:%S"), oid, None))
        eid += 1

# logins, deposits, kyc, scattered randomly across users/dates
for uid in range(1, 201):
    n_logins = random.randint(1, 25)
    for _ in range(n_logins):
        ts = base_date + timedelta(days=random.randint(0, 220), hours=random.randint(0, 23))
        variant = random.choice(event_type_variants["login"])
        events.append((eid, uid, variant, ts.strftime("%Y-%m-%dT%H:%M:%S"), None, None))
        eid += 1
    if random.random() < 0.6:
        ts = base_date + timedelta(days=random.randint(0, 220))
        variant = random.choice(event_type_variants["deposit"])
        amt = round(random.uniform(50, 5000), 2)
        events.append((eid, uid, variant, ts.strftime("%Y-%m-%dT%H:%M:%S"), None, f'{{"amount_usd":{amt}}}'))
        eid += 1
    if random.random() < 0.4:
        ts = base_date + timedelta(days=random.randint(0, 220))
        variant = random.choice(event_type_variants["kyc_submitted"])
        events.append((eid, uid, variant, ts.strftime("%Y-%m-%dT%H:%M:%S"), None, None))
        eid += 1

cur.executemany("INSERT INTO raw_events VALUES (?,?,?,?,?,?)", events)

conn.commit()

# Quick sanity check
print("users:", cur.execute("SELECT COUNT(*) FROM users").fetchone()[0])
print("orders:", cur.execute("SELECT COUNT(*) FROM orders").fetchone()[0])
print("raw_events:", cur.execute("SELECT COUNT(*) FROM raw_events").fetchone()[0])
print("distinct event_type spellings:", cur.execute("SELECT COUNT(DISTINCT event_type) FROM raw_events").fetchone()[0])
print(cur.execute("SELECT DISTINCT event_type FROM raw_events ORDER BY event_type").fetchall())

conn.close()
