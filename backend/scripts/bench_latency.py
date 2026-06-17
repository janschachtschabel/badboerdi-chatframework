"""Mini-Latenz-Benchmark gegen das LOKALE Backend (Throwaway).

Feuert pro Gesprächstyp REPEATS echte Turns und meldet die MIN-Latenz
(robust gegen Upstream-Spikes) + Pattern. Wird je Konfiguration (Modell ×
Reranker) einmal aufgerufen; Vergleich erfolgt extern.
"""
import json, sys, urllib.request, uuid, time
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PROMPTS = [
    ("Wissen (RAG)",     "Was ist OER?"),
    ("Suche (MCP+Gate)", "Suche Arbeitsblätter zu Photosynthese"),
    ("Orientierung",     "Was kannst du eigentlich?"),
]
REPEATS = 2

def chat(msg):
    body = json.dumps({
        "session_id": "bench-" + uuid.uuid4().hex[:8],
        "message": msg,
        "environment": {"page_url": "https://staging.openeduhub.net/"},
    }).encode()
    req = urllib.request.Request(
        "http://127.0.0.1:8000/api/chat", data=body,
        headers={"Content-Type": "application/json"})
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=180) as r:
        d = json.loads(r.read())
    dt = (time.perf_counter() - t0) * 1000
    return dt, ((d.get("debug") or {}).get("pattern") or "?")

label_arg = sys.argv[1] if len(sys.argv) > 1 else "(Konfig)"
print(f"=== {label_arg} ===")
total = 0.0
for label, msg in PROMPTS:
    runs = []
    pat = "?"
    for _ in range(REPEATS):
        dt, pat = chat(msg)
        runs.append(dt)
    best = min(runs)
    total += best
    print(f"  {label:18s} min={best:6.0f}ms  runs={[round(t) for t in runs]}  {pat}")
print(f"  {'SUMME (min)':18s} {total:6.0f}ms")
