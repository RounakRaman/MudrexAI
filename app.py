"""
Mudrex PM Internship Prep Project
----------------------------------
A working "events schema cleanup + natural language to SQL + auto-chart" tool.

Three things this demonstrates, matching the internship's own task list:
1. Cleaning up a messy events schema (inconsistent event_type naming, mixed
   timestamp formats) using SQL CTEs.
2. Turning a natural language question into SQL automatically, using an LLM
   (Groq, LLaMA 3.3 70B) instead of a human writing ad-hoc SQL every time.
3. Auto-charting the result so a non-technical stakeholder gets an answer,
   not a raw table.

Run with: streamlit run app.py
Needs: GROQ_API_KEY environment variable set.
"""

import streamlit as st
import sqlite3
import pandas as pd
import json
import os
from groq import Groq

DB_PATH = os.path.join(os.path.dirname(__file__), "mudrex_events.db")

st.set_page_config(page_title="Mudrex Events Insight Tool", layout="wide")

# ---------------------------------------------------------------------------
# 1. SCHEMA CLEANUP LAYER
#
# The raw_events table has 17 different spellings of 6 real event types,
# plus timestamps in two different formats. Rather than cleaning the table
# once and losing the raw data, we expose a CLEAN VIEW via a CTE-backed
# SQL query. Anyone (or any AI-generated query) can query `cleaned_events`
# as if it were a tidy table, while the underlying raw_events stays
# untouched as the source of truth. This is the standard real-world pattern:
# don't mutate raw data, build a clean abstraction on top of it.
# ---------------------------------------------------------------------------

CLEANED_EVENTS_CTE = """
WITH cleaned_events AS (
    SELECT
        event_id,
        user_id,
        CASE
            WHEN LOWER(event_type) IN ('order_placed', 'orderplaced') THEN 'order_placed'
            WHEN LOWER(event_type) IN ('order_filled', 'orderfilled') THEN 'order_filled'
            WHEN LOWER(event_type) IN ('order_cancelled', 'ordercancelled') THEN 'order_cancelled'
            WHEN LOWER(event_type) IN ('login', 'user_login') THEN 'login'
            WHEN LOWER(event_type) IN ('deposit', 'fundsdeposited') THEN 'deposit'
            WHEN LOWER(event_type) = 'kyc_submitted' THEN 'kyc_submitted'
            ELSE LOWER(event_type)
        END AS event_type,
        -- normalize the two timestamp formats (ISO and DD-MM-YYYY HH:MM:SS)
        -- into a single comparable format
        CASE
            WHEN event_ts LIKE '__-__-____ %' THEN
                substr(event_ts, 7, 4) || '-' || substr(event_ts, 4, 2) || '-' || substr(event_ts, 1, 2)
                || ' ' || substr(event_ts, 12, 8)
            ELSE REPLACE(event_ts, 'T', ' ')
        END AS event_ts_clean,
        order_id
    FROM raw_events
),
deduped_events AS (
    -- collapse accidental duplicate event rows (same user, type, order, timestamp)
    SELECT DISTINCT user_id, event_type, event_ts_clean, order_id
    FROM cleaned_events
)
SELECT * FROM deduped_events
"""


def get_connection():
    return sqlite3.connect(DB_PATH)


def run_raw_sql(sql: str) -> pd.DataFrame:
    """Run arbitrary SQL (used by the AI-generated queries) against the DB,
    with the cleaned_events CTE available as a usable table-like alias."""
    conn = get_connection()
    try:
        # Make the cleaned view queryable as if it were a real table by
        # wrapping whatever SQL the model writes around our CTE definition.
        full_sql = CLEANED_EVENTS_CTE.replace(
            "SELECT * FROM deduped_events", f"SELECT * FROM deduped_events) {sql}"
        ) if sql.strip().lower().startswith("select") and "cleaned_events" in sql.lower() else sql

        # Simpler, more robust approach: always make cleaned_events available
        # as a temp view, then run the model's SQL untouched against it.
        conn.execute("DROP VIEW IF EXISTS cleaned_events")
        view_sql = "CREATE TEMP VIEW cleaned_events AS\n" + CLEANED_EVENTS_CTE.split("SELECT * FROM deduped_events")[0] + "SELECT * FROM deduped_events"
        conn.execute(view_sql)
        df = pd.read_sql_query(sql, conn)
        return df
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 2. NATURAL LANGUAGE -> SQL LAYER (via Groq)
#
# This is the core "AI tool to automate querying" piece. We give the model
# the schema (including the cleaned_events view) and ask it to return ONLY
# a SQL query, nothing else. This mirrors exactly what the internship
# describes: "turn data requests into insights without manual SQL."
# ---------------------------------------------------------------------------

SCHEMA_DESCRIPTION = """
You have access to these tables/views in a SQLite database:

1. users(user_id, signup_ts, country, plan_tier, kyc_status)
   - plan_tier is one of: free, pro, elite
   - kyc_status is one of: verified, pending, rejected, or NULL

2. orders(order_id, user_id, asset, side, qty, price, status, created_ts, updated_ts)
   - asset is one of: BTC, ETH, SOL, USDT, XRP
   - side is 'buy' or 'sell'
   - status is one of: filled, cancelled, pending, failed

3. cleaned_events(user_id, event_type, event_ts_clean, order_id)
   - This is a CLEANED VIEW of a messy raw_events table. Always use this
     view, never raw_events directly, since event_type here is already
     normalized to: order_placed, order_filled, order_cancelled, login,
     deposit, kyc_submitted.
   - event_ts_clean is a normalized timestamp string in 'YYYY-MM-DD HH:MM:SS' format.

Write ONE SQLite query that answers the user's question. Use CTEs and window
functions where appropriate (e.g. ROW_NUMBER, RANK, LAG/LEAD, running SUM)
when the question calls for "most recent", "first", "rank", "running total",
or similar.

Return ONLY the raw SQL query. No markdown formatting, no backticks, no
explanation, no preamble. Just the SQL.
"""


def generate_sql(question: str, api_key: str) -> str:
    client = Groq(api_key=api_key)
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": SCHEMA_DESCRIPTION},
            {"role": "user", "content": question},
        ],
        temperature=0,
        max_tokens=500,
    )
    sql = response.choices[0].message.content.strip()
    # strip accidental markdown fences if the model adds them anyway
    sql = sql.replace("```sql", "").replace("```", "").strip()
    return sql


def suggest_chart_type(question: str, df: pd.DataFrame, api_key: str) -> dict:
    """Ask the model what chart type best fits the result, returning
    structured JSON: {"chart_type": "...", "x": "...", "y": "...", "reason": "..."}"""
    client = Groq(api_key=api_key)
    cols = list(df.columns)
    sample = df.head(5).to_dict(orient="records")
    prompt = f"""
Question asked: {question}
Result columns: {cols}
Sample rows: {json.dumps(sample, default=str)}

Pick the best chart type for this data: one of "bar", "line", "none" (if a
table is more appropriate, e.g. single value or single row result).
Respond ONLY with JSON, no markdown, in this exact shape:
{{"chart_type": "bar|line|none", "x": "<column name or null>", "y": "<column name or null>", "reason": "<one sentence>"}}
"""
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        max_tokens=200,
    )
    text = response.choices[0].message.content.strip()
    text = text.replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"chart_type": "none", "x": None, "y": None, "reason": "Could not parse chart suggestion."}


# ---------------------------------------------------------------------------
# 3. STREAMLIT UI
# ---------------------------------------------------------------------------

st.title("Mudrex Events Insight Tool")
st.caption("Ask a question in plain English. Get SQL, a result, and a chart. No manual querying.")

api_key = os.environ.get("GROQ_API_KEY", "")
with st.sidebar:
    st.header("Setup")
    if not api_key:
        api_key = st.text_input("Groq API key", type="password")
    st.markdown("---")
    st.subheader("Schema (cleaned)")
    st.code(SCHEMA_DESCRIPTION, language="text")
    st.markdown("---")
    st.subheader("Try asking:")
    st.markdown("""
    - How many users signed up each month?
    - What's the most recent event for each user, top 10 by recency?
    - Which asset has the highest total filled order volume?
    - Show daily active users (logins) over the last 30 days as a trend
    - Rank users by total deposit amount
    - What % of orders get cancelled, by asset?
    """)

question = st.text_input("Ask a question about the data:", placeholder="e.g. Which asset has the highest filled order volume?")

col_run, col_clear = st.columns([1, 5])
run_clicked = col_run.button("Run", type="primary")

if run_clicked and question:
    if not api_key:
        st.error("Add a Groq API key in the sidebar first.")
    else:
        with st.spinner("Generating SQL..."):
            try:
                sql = generate_sql(question, api_key)
            except Exception as e:
                st.error(f"SQL generation failed: {e}")
                sql = None

        if sql:
            st.subheader("Generated SQL")
            st.code(sql, language="sql")

            with st.spinner("Running query..."):
                try:
                    df = run_raw_sql(sql)
                except Exception as e:
                    st.error(f"Query execution failed: {e}")
                    df = None

            if df is not None:
                st.subheader("Result")
                st.dataframe(df, use_container_width=True)

                if len(df) > 1 and len(df.columns) >= 2:
                    with st.spinner("Picking a chart..."):
                        try:
                            chart_spec = suggest_chart_type(question, df, api_key)
                        except Exception as e:
                            chart_spec = {"chart_type": "none", "reason": str(e)}

                    if chart_spec.get("chart_type") in ("bar", "line") and chart_spec.get("x") in df.columns and chart_spec.get("y") in df.columns:
                        st.subheader("Chart")
                        st.caption(chart_spec.get("reason", ""))
                        chart_df = df.set_index(chart_spec["x"])[[chart_spec["y"]]]
                        if chart_spec["chart_type"] == "bar":
                            st.bar_chart(chart_df)
                        else:
                            st.line_chart(chart_df)

st.markdown("---")
st.subheader("Manual SQL (for your own practice)")
manual_sql = st.text_area("Write your own SQL against `cleaned_events`, `users`, `orders`:", height=120,
                            placeholder="WITH ... SELECT * FROM cleaned_events LIMIT 10;")
if st.button("Run manual SQL"):
    try:
        df_manual = run_raw_sql(manual_sql)
        st.dataframe(df_manual, use_container_width=True)
    except Exception as e:
        st.error(f"Error: {e}")
