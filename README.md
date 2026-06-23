# Mudrex Events Insight Tool — Interview Prep Project

## What this is
A working tool that mirrors all three things Mudrex's internship JD asks for:
1. Cleans up a messy events schema (17 inconsistent spellings of 6 event types, mixed timestamp formats)
2. Turns a plain-English question into SQL automatically using Groq (LLaMA 3.3 70B)
3. Auto-suggests and renders a chart for the result

## How to run it
```
pip install -r requirements.txt
export GROQ_API_KEY=your_key_here
streamlit run app.py
```
(Or skip the export and paste your key into the sidebar text box when it opens.)

The database (`mudrex_events.db`) is already generated and included. If you want
to regenerate it with different random data, run `python3 generate_db.py` first.

## What you MUST be able to explain tomorrow, in your own words

**1. Why a CTE instead of just cleaning the table once?**
The raw_events table stays untouched as the source of truth. The `cleaned_events`
CTE/view is a non-destructive abstraction layer on top of messy data. This is the
real-world pattern: you never want to silently overwrite raw logs, because if your
cleaning logic has a bug, you've destroyed the original signal. Look at the CASE
statement in `CLEANED_EVENTS_CTE` in app.py — it's just a lookup table mapping every
messy spelling to one canonical value.

**2. Why ROW_NUMBER() OVER (PARTITION BY ...)?**
This is THE pattern for "most recent X per Y" or "first/last event per user."
PARTITION BY user_id means "restart the numbering for each user." ORDER BY
event_ts_clean DESC means "rank 1 = most recent." Then you filter WHERE rn = 1.
This is different from GROUP BY because GROUP BY can only return aggregates
(COUNT, SUM, MAX) — it can't return "the whole row where the timestamp is the max"
without extra subqueries. Window functions let you rank/number rows while keeping
every column.

**3. How the NL-to-SQL piece works.**
We send the model a schema description (not the data, just table/column names and
what values they take) plus the user's question, and ask it to return only SQL.
The model never sees real user data, just structure. This matters if asked about
data privacy/security in an AI tool — a real concern for a regulated crypto platform.

**4. The honest limitation.**
This is a prototype on synthetic data, not a production system. If asked "what
would you change for production," have an answer ready: schema validation before
running model-generated SQL (to block destructive queries), caching repeated
questions, handling ambiguous questions by asking a clarifying question back
instead of guessing, and query cost/timeout limits since LLM-generated SQL on a
real warehouse could be expensive or slow.

## Practice questions to run through the tool tonight
- How many users signed up each month?
- What's the most recent event for each user, top 10 by recency?
- Which asset has the highest total filled order volume?
- Rank users by total deposit amount
- What % of orders get cancelled, by asset?

Run each one, read the generated SQL, and ask yourself: could I have written this
myself? If not, that's exactly where to focus your remaining hours.
