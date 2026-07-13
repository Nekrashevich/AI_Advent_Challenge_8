import time
import uuid
from collections import defaultdict
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from budget_agent import analyze, data

MAX_HISTORY = 8
RATE_LIMIT = 8
RATE_WINDOW = 60

app = FastAPI(title="Local Budget AI", version="0.1.0")
sessions = {}
rate_store = defaultdict(list)


PAGE = """<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Local Budget AI</title>
<style>
body{margin:0;font-family:system-ui,Segoe UI,sans-serif;background:#111827;color:#e5e7eb}
main{max-width:820px;margin:0 auto;padding:24px}
h1{font-size:22px;margin:0 0 4px}.sub{color:#9ca3af;margin-bottom:18px}
#log{height:54vh;overflow:auto;border:1px solid #374151;border-radius:10px;padding:14px;background:#0b1220}
.m{padding:10px 12px;border-radius:8px;margin:8px 0;line-height:1.45;white-space:pre-wrap}
.u{background:#1f2937;margin-left:15%}.b{background:#172554;margin-right:15%}
form{display:flex;gap:8px;margin-top:12px}input{flex:1;padding:12px;border-radius:8px;border:1px solid #374151;background:#0b1220;color:#e5e7eb}
button{padding:0 18px;border:0;border-radius:8px;background:#60a5fa;color:#0b1220;font-weight:700}
.meta{font-size:12px;color:#9ca3af;margin-top:10px}
</style>
</head>
<body><main>
<h1>Local Budget AI</h1>
<div class="sub">Локальный анализатор расходов: Ollama + RAG по CSV</div>
<div id="log"><div class="meta">Спроси: почему в июне выросли расходы?</div></div>
<form id="f"><input id="q" placeholder="Вопрос по расходам..." autocomplete="off"><button>Спросить</button></form>
<div class="meta">API: GET /health, POST /chat. Rate limit: 8 запросов/мин на IP.</div>
</main>
<script>
let sid=null; const log=document.getElementById('log'), q=document.getElementById('q');
function add(c,t){const d=document.createElement('div');d.className='m '+c;d.textContent=t;log.appendChild(d);log.scrollTop=log.scrollHeight}
document.getElementById('f').onsubmit=async e=>{e.preventDefault(); const text=q.value.trim(); if(!text)return;
add('u',text); q.value=''; add('b','думаю...');
try{const r=await fetch('/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:text,session_id:sid})});
const d=await r.json(); sid=d.session_id||sid; log.lastChild.textContent=d.reply||d.detail||'ошибка';}
catch(err){log.lastChild.textContent='сервер не ответил'}};
</script></body></html>"""


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None


class ChatResponse(BaseModel):
    reply: str
    session_id: str
    history_len: int
    response_time: float
    sources: int


def _client_ip(request):
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _check_rate(ip):
    now = time.time()
    rate_store[ip] = [t for t in rate_store[ip] if now - t < RATE_WINDOW]
    if len(rate_store[ip]) >= RATE_LIMIT:
        return False
    rate_store[ip].append(now)
    return True


def answer_message(message, session_id=None):
    sid = session_id or uuid.uuid4().hex
    history = sessions.get(sid, [])
    question = message.strip()
    if not question:
        raise ValueError("empty message")
    started = time.time()
    result = analyze.answer_with_rag(question, compare_cloud=False)
    reply = result["local_answer"]
    history.append({"role": "user", "content": question})
    history.append({"role": "assistant", "content": reply})
    sessions[sid] = history[-MAX_HISTORY:]
    return {
        "reply": reply,
        "session_id": sid,
        "history_len": len(sessions[sid]),
        "response_time": round(time.time() - started, 2),
        "sources": len(result["hits"]),
    }


@app.get("/", response_class=HTMLResponse)
def index():
    return PAGE


@app.get("/health")
def health():
    rows = data.load_expenses()
    return {
        "status": "ok",
        "service": "local-budget-ai",
        "transactions": len(rows),
        "active_sessions": len(sessions),
        "rate_limit": f"{RATE_LIMIT}/min per IP",
    }


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest, request: Request):
    if not _check_rate(_client_ip(request)):
        raise HTTPException(status_code=429, detail=f"Rate limit: max {RATE_LIMIT} req/min")
    if len(req.message) > 800:
        raise HTTPException(status_code=400, detail="Message is too long, max 800 characters")
    try:
        return answer_message(req.message, req.session_id)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=502, detail=str(error)) from error


def run():
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    run()
