# Mudrex Events Insight Tool: Interview Prep Project

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
