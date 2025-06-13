import os, random, uuid, requests
import streamlit as st
import pandas as pd
from supabase import create_client
# supabase credentials come from .streamlit/secrets.toml
SUPA_URL = st.secrets["supabase"]["url"]
SUPA_KEY = st.secrets["supabase"]["key"]
supabase = create_client(SUPA_URL, SUPA_KEY)

if "user_id" not in st.session_state:
    # Generates a random UUID once per new session
    st.session_state.user_id = str(uuid.uuid4())


CANDIDATE = "Pete Buttigieg"
NUM_EXPOSURES = 10

NEWSAPI_KEY = os.getenv("NEWSAPI_KEY")
if not NEWSAPI_KEY:
    st.error("Please set your NEWSAPI_KEY environment variable.")
    st.stop()

@st.cache_data(ttl=3600)
def fetch_live_exposures(query: str, max_articles: int = 1):
    url = "https://newsapi.org/v2/everything"
    params = {
        # only match in titles
        "qInTitle": query,
        "language": "en",
        "sortBy":   "publishedAt",
        "pageSize": max_articles,
        "apiKey":   NEWSAPI_KEY,
    }
    r = requests.get(url, params=params)
    r.raise_for_status()
    articles = r.json().get("articles", [])
    exps = []
    for art in articles:
        title = art.get("title", "")
        desc  = art.get("description") or art.get("content") or ""
        if title and desc:
            exps.append({"headline": title, "summary": desc})
    return exps


# — SESSION STATE DEFAULTS —
for k,v in {
    "phase": "init",
    "start_slider": 50.0,
    "start_score": None,
    "exposures": [],
    "idx": 0,
    "responses": []
}.items():
    if k not in st.session_state:
        st.session_state[k] = v

# — CALLBACKS —
def begin_callback():
    st.session_state.start_score = st.session_state.start_slider
    live = fetch_live_exposures(CANDIDATE, max_articles=10)
    # if NewsAPI returns fewer than NUM_EXPOSURES, take them all
    sampled = random.sample(live, min(len(live), NUM_EXPOSURES))
    st.session_state.exposures = sampled
    st.session_state.idx       = 0
    st.session_state.responses = []
    st.session_state.phase     = "survey"

def next_callback():
    i = st.session_state.idx
    key = f"slider_{i}"
    st.session_state.responses.append(st.session_state[key])
    st.session_state.idx += 1
    if st.session_state.idx >= len(st.session_state.exposures):
        st.session_state.phase = "done"

# — UTILITY —
def compute_level(start, responses):
    deltas = [abs(r-start) for r in responses]
    avg = sum(deltas)/len(deltas) if deltas else 0
    if avg > 20: return 1,"Flip-Flopper"
    if avg > 10: return 2,"Malleable Mind"
    if avg > 5:  return 3,"Moderately Moved"
    if avg > 2:  return 4,"Steady Supporter"
    return (5,"Buttigieg Stan") if start>=80 else (4,"Steady Supporter")

# — INIT PAGE —
if st.session_state.phase=="init":
    st.title(f"{CANDIDATE} Impression Tracker")
    st.write(f"On a 0–100 scale, how much do you like **{CANDIDATE}** right now?")
    st.slider(
        "Your starting impression:",
        min_value=0.0, max_value=100.0, step=0.1,
        key="start_slider"
    )
    st.button("Begin", on_click=begin_callback)

# — SURVEY PAGE —
elif st.session_state.phase=="survey":
    i   = st.session_state.idx
    exp = st.session_state.exposures[i]
    st.header(f"Story {i+1} of {len(st.session_state.exposures)}")
    st.subheader(exp["headline"])
    st.write(exp["summary"])

    skey = f"slider_{i}"
    if skey not in st.session_state:
        st.session_state[skey] = float(st.session_state.start_score if i==0 else st.session_state.responses[-1])
    st.slider(
        f"After seeing this story, how much do you like {CANDIDATE}?",
        0.0, 100.0, step=0.1, key=skey
    )
    st.button("Next", on_click=next_callback)

# — FINAL PAGE —
else:
    st.title("All Done! 🎉")
    start = st.session_state.start_score
    resp  = st.session_state.responses
    level, label = compute_level(start, resp)

    st.markdown(f"## Your Buttigieg Score: **{level} – {label}**")
    st.write(f"- Start: **{start:.1f}** • End: **{resp[-1]:.1f}** • Δ avg: **{sum(abs(r-start) for r in resp)/len(resp):.1f}**")

    # build payload
    payload = []
    for i, e in enumerate(st.session_state.exposures):
        payload.append({
            "user_id":       st.session_state.user_id,
            "initial_score": start,
            "snippet_i":     i,
            "headline":      e["headline"],
            "summary":       e["summary"],
            "rating":        resp[i]
        })

    # try inserting…
    try:
        res = supabase.table("infdriven").insert(payload).execute()
    except Exception as err:
        st.error(f"❌ Exception when saving: {err}")
    else:
        # res.error will be None on success
        if getattr(res, "error", None):
            st.error(f"❌ Failed to save: {res.error}")
        else:
            st.success("✅ Your responses have been saved!")

    # optional: still let them download
    df = pd.DataFrame(payload)
    st.download_button(
        "Download your session data",
        data=df.to_csv(index=False),
        file_name="buttigieg_session.csv",
        mime="text/csv"
    )
