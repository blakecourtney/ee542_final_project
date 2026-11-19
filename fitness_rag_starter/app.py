import json
import os
import sys
from pathlib import Path

import faiss
import httpx
import numpy as np
import streamlit as st
from sentence_transformers import SentenceTransformer
from rag.retriever import retrieve_diverse

ROOT = Path(__file__).resolve().parent
GARMIN_ROOT = ROOT.parent / 'code' / 'garmin-ingest'
sys.path.insert(0, str(GARMIN_ROOT))
from garmin_ingest.context import get_athlete_context

BASE_URL = os.getenv('LLM_API_BASE', 'http://127.0.0.1:8001/v1').rstrip('/')
EMBED_MODEL = 'sentence-transformers/all-MiniLM-L6-v2'

st.set_page_config(page_title='Fitness AI Coach', page_icon='🏃', layout='wide')
st.markdown('''<style>
.block-container {padding-top: 1.6rem; max-width: 1150px;}
[data-testid="stMetricValue"] {font-size: 1.55rem;}
</style>''', unsafe_allow_html=True)

@st.cache_resource(show_spinner='Loading fitness knowledge base...')
def load_knowledge():
    path = ROOT / 'index_v2' / 'fitness.faiss'
    if not path.exists():
        raise FileNotFoundError('Missing index_v2/fitness.faiss. Run python3 rag/build_index.py')
    index = faiss.read_index(str(path))
    chunks = json.loads((ROOT / 'index_v2' / 'chunks.json').read_text(encoding='utf-8'))
    if index.ntotal != len(chunks):
        raise ValueError('FAISS index and chunks.json are out of sync')
    encoder = SentenceTransformer(EMBED_MODEL)
    return index, chunks, encoder

@st.cache_data(ttl=60, show_spinner=False)
def athlete_data():
    return get_athlete_context()

def get_model():
    with httpx.Client(timeout=10) as client:
        response = client.get(f'{BASE_URL}/models')
        response.raise_for_status()
        return os.getenv('LLM_MODEL') or response.json()['data'][0]['id']

def fmt(value, suffix='', decimals=0):
    if value is None:
        return 'N/A'
    return f'{value:,.{decimals}f}{suffix}' if isinstance(value, (float, int)) else str(value)

SYSTEM_PROMPT = '''You are a helpful, evidence-based fitness coaching assistant. Your input includes retrieved research passages and structured Garmin data.
Only use recorded Garmin measurements; null means missing, never zero. Never invent training sessions, sleep, HRV, recovery values, or goals. Preserve exact activity types (walking is not cycling). Do not treat absence of a recorded strength session as proof none occurred. Values ending _vs_avg are absolute differences, not percentages.
Distinguish observations, interpretations and suggestions. Garmin Body Battery ranges from 5 to 100; a value of 5 is at the low end of the scale. A single metric does not diagnose overtraining or illness. If Body Battery is very low, resting HR is notably above baseline, or recovery information is incomplete, prioritize rest or easy activity and reassessment over intense training. Do not recommend both more high-intensity work and immediate recovery without clearly separating today's advice from longer-term goals. Do not overstate conclusions from missing metrics.
Cite factual training guidance using [1], [2] etc, referring ONLY to the numbered retrieved passages. Never invent a citation or cite a passage that does not support the claim. Be concise, friendly, specific, and practical. When a user asks for a workout, provide an actionable conservative suggestion and explain why. If the user reports concerning symptoms, recommend appropriate professional medical evaluation. Do not present this tool as medical advice.'''

def coach_answer(question, history, athlete, index, chunks, encoder, model):
    hits = retrieve_diverse(question, encoder, index, chunks, candidate_k=12, final_k=5, max_per_document=2)
    passages = '\n\n'.join(
        f'[{n}] {doc.get("title", "Source")} | {doc.get("section", "")} | {doc.get("source_url", "")}\n{doc.get("text", "")[:1600]}'
        for n, (doc, _) in enumerate(hits, 1)
    )
    recent_history = history[-4:]
    messages = [{'role': 'system', 'content': SYSTEM_PROMPT}]
    for item in recent_history:
        messages.append({'role': item['role'], 'content': item['content'][:2500]})
    messages.append({'role': 'user', 'content':
        f'ATHLETE DATA (may be unavailable):\n{json.dumps(athlete, default=str)}\n\n'
        f'RETRIEVED FITNESS KNOWLEDGE:\n{passages}\n\n'
        f'USER QUESTION:\n{question}\n\n'
        'Answer using the athlete data and relevant knowledge. Use numbered citations only when supported.'})
    with httpx.Client(timeout=180) as client:
        result = client.post(f'{BASE_URL}/chat/completions', json={
            'model': model, 'messages': messages, 'temperature': 0.15,
            'max_tokens': 600
        })
        result.raise_for_status()
        answer = result.json()['choices'][0]['message']['content']
    sources = []
    for n, (doc, score) in enumerate(hits, 1):
        sources.append({'number': n, 'title': doc.get('title', 'Fitness research'),
                        'url': doc.get('source_url', ''), 'section': doc.get('section', ''),
                        'score': float(score)})
    return answer, sources

st.title('🏃 Fitness AI Coach')
st.caption('Garmin-powered training insights · Research-backed answers · Local Llama AI')

try:
    index, chunks, encoder = load_knowledge()
except Exception as exc:
    st.error(f'Knowledge base could not load: {exc}')
    st.stop()

try:
    athlete = athlete_data()
    athlete_error = None
except Exception as exc:
    athlete = None
    athlete_error = str(exc)

try:
    model = get_model()
    model_error = None
except Exception as exc:
    model = None
    model_error = str(exc)

with st.sidebar:
    st.header('Athlete dashboard')
    if athlete_error:
        st.warning('Garmin data unavailable')
        st.caption(athlete_error)
    elif athlete:
        st.caption(f'As of {athlete.get("as_of", "latest sync")}')
        week = athlete.get('last_7_days') or {}
        recovery = athlete.get('recovery') or {}
        a, b = st.columns(2)
        a.metric('Sessions · 7 days', fmt(week.get('sessions')))
        b.metric('Training hours', fmt(week.get('hours'), decimals=1))
        a, b = st.columns(2)
        a.metric('Training load', fmt(week.get('training_load')))
        b.metric('Resting HR', fmt(recovery.get('resting_hr'), ' bpm'))
        st.metric('Body Battery peak', fmt(recovery.get('body_battery_peak'), ' / 100'))
        st.caption('Metrics are shown as recorded. Missing values are not estimated.')
        with st.expander('Recent recorded activities'):
            for session in (athlete.get('recent_sessions') or [])[:7]:
                st.write(f"**{session.get('date', '')}** · {session.get('type', 'Activity').replace('_', ' ')} · {session.get('duration_min', '?')} min")
    else:
        st.info('No Garmin data loaded')
    st.divider()
    st.write(f'**Knowledge base:** {len(chunks)} passages')
    st.write(f'**Sources:** {len(set(c.get("document_id") for c in chunks))} documents')
    st.write('**LLM:** ' + ('Connected' if model else 'Offline'))
    if model_error:
        st.caption(f'LLM server: {model_error}')
    if st.button('Refresh Garmin data'):
        athlete_data.clear()
        st.rerun()
    if st.button('Clear conversation'):
        st.session_state.messages = []
        st.rerun()

if 'messages' not in st.session_state:
    st.session_state.messages = []

if not st.session_state.messages:
    st.info('Ask about your training history, your next workout, or recovery. The coach uses available Garmin metrics and research passages.')
    st.markdown('**Try a question:**')
    suggestions = [
        'Based on my recent Garmin activities and recovery data, what should my next workout be?',
        'How can I balance running and strength training this week?',
        'What do my resting heart rate and Body Battery suggest about recovery?',
    ]
    for i, suggestion in enumerate(suggestions):
        if st.button(suggestion, key=f'suggestion_{i}', use_container_width=True):
            st.session_state.pending_question = suggestion
            st.rerun()

for message in st.session_state.messages:
    with st.chat_message(message['role']):
        st.markdown(message['content'])
        if message.get('sources'):
            with st.expander('Research and Garmin documentation'):
                for src in message['sources']:
                    title = f"[{src['number']}] {src['title']} — {src['section']}"
                    if src['url'].startswith(('https://', 'http://')):
                        st.markdown(f"{title}: [Open source]({src['url']})")
                    else:
                        st.write(title)

question = st.chat_input('Ask your fitness coach...')
if not question:
    question = st.session_state.pop('pending_question', None)
if question:
    st.chat_message('user').markdown(question)
    prior = st.session_state.messages.copy()
    st.session_state.messages.append({'role': 'user', 'content': question})
    with st.chat_message('assistant'):
        if not model:
            answer = 'The local Llama server is offline. Start llama-server on port 8001 and refresh this page.'
            sources = []
            st.error(answer)
        else:
            with st.spinner('Analyzing Garmin data and fitness research...'):
                try:
                    answer, sources = coach_answer(question, prior, athlete, index, chunks, encoder, model)
                    st.markdown(answer)
                    if sources:
                        with st.expander('Research and Garmin documentation'):
                            for src in sources:
                                title = f"[{src['number']}] {src['title']} — {src['section']}"
                                if src['url'].startswith(('https://', 'http://')):
                                    st.markdown(f"{title}: [Open source]({src['url']})")
                                else:
                                    st.write(title)
                except Exception as exc:
                    answer = f'Unable to generate an answer: {exc}'
                    sources = []
                    st.error(answer)
    st.session_state.messages.append({'role': 'assistant', 'content': answer, 'sources': sources})
