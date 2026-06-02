# Betriebskosten-Kalkulation BadBoerdi-Chatbot

**Stand: Mai 2026** · Kalkulationsbasis: 5 Selbst-Evaluations-Runs mit je 144 Turns (720 Turns insgesamt) · OpenAI-Preise und Hosting-Marktpreise zum Recherchedatum.

---

## 1. Methodik & Annahmen

### 1.1 Datengrundlage

Token-Verbrauch wurde aus 5 automatisierten Persona-Eval-Runs der letzten Wochen ermittelt (`debug.token_usage` pro Turn). Das ist ein realistischer Worst-Case-Mix: 9 Personas × 13 Intents × 1 Turn, alle Such-/Erstell-/Faktenfragen-Pfade. **Real-User-Sessions sind eher kürzer** (typisch 3–5 Folge-Fragen statt komplette Persona-Drilldowns).

Die Selbstevaluation misst zusätzlich die **Treffgenauigkeit auf Persona, Pattern, Intent etc.** mittels „LLM-as-Judge" — daraus ergibt sich der Quality-Score je Modell (siehe § 2.1).

### 1.2 Token-Statistik pro Turn (Mittelwert)

| Phase | Prompt | davon Cached | Completion | LLM-Calls |
|---|---:|---:|---:|---:|
| `classify` (Klassifikator) | 10.402 | 9.728 (94 %) | 166 | 1,0 |
| `tool_loop` (Hauptantwort + MCP) | 26.438 | 17.365 (66 %) | 184 | 1,7 |
| `response` (Reflection) | 13.923 | 6.984 (50 %) | 110 | 1,0 (nur 17 % der Turns) |
| `quick_replies` (Folge-Fragen) | 2.217 | 46 (2 %) | 232 | 1,0 (27 % der Turns) |
| **Gesamt pro Turn** | **32.881** | **23.735 (72 %)** | **383** | **~2–3** |

**Perzentile** (Total-Tokens/Turn): p50 = 25.661 · p95 = 75.531 · p99 = 79.931

→ Die hohe Cache-Hit-Rate (72 % der Prompt-Tokens) drückt die effektiven Input-Kosten massiv. Sie kommt vom 6-Schichten-Schema: System-Prompt + Persona + Pattern-Defs + RAG-Context werden über die Turns hinweg wiederverwendet.

### 1.3 Annahmen für die Hochrechnung

| Parameter | Annahme | Begründung |
|---|---:|---|
| Jährliche WLO-Besucher | ≈ 1 Mio | User-Schätzung |
| Tagesbesucher | 2.500 | 1 Mio / 365 ≈ 2.740 (Mittel der User-Vorgabe 2.000–3.000) |
| Anteil mit Chat-Nutzung | 20 % | Konservativ-mittel; Branchenwerte für Onsite-Chatbots: 10–30 % |
| Tägliche Chat-Sessions | 500 | 2.500 × 20 % |
| Turns pro Session | 4 | Kurzer Smalltalk: 1–2 · Kurze Suche: 3–5 · Tiefe Recherche: 6–10 |
| **Turns pro Tag** | **2.000** | 500 × 4 |
| Tage pro Monat | 30 | |
| **Turns pro Monat** | **60.000** | 2.000 × 30 |

**Sensitivitäts-Hinweis:** Die Rechnung skaliert linear. Bei 10 % Adoption nur die Hälfte, bei 30 % Adoption das 1,5-fache. Bei längeren Sessions (8 statt 4 Turns) verdoppeln sich die Token-Kosten.

---

## 2. Variable Kosten — OpenAI Token-Gebühren

### 2.1 Modell-Quality (Selbst-Evaluation, LLM-as-Judge)

Die in den Chatbot integrierte Selbstevaluation misst die Treffgenauigkeit auf Persona-, Intent- und Pattern-Klassifikation sowie die inhaltliche Antwortqualität. Ergebnisse für die OpenAI-Mini-Modelle (über 144 Eval-Turns je Modell):

| Modell | Eval-Score | Verfügbar in der B-API? | Bemerkung |
|---|:---:|:---:|---|
| **gpt-4.1-mini** | **80 %** | ✅ ja | empfohlen — bestes Preis-Leistungs-Quality-Verhältnis |
| gpt-5-mini | 72 % | ❌ nein | nicht ohne Architektur-Umbau verfügbar; zudem geringste Qualität |
| gpt-5.4-mini (aktuell aktiv) | 84 % | ❌ nein | beste Qualität, aber deutlich teurer und nur über die direkte OpenAI-API |

**Kontext B-API:** das Backend ist im Ist-Stand auf eine **Bildungs-API** (B-API; OpenAI-kompatibles Gateway über OAuth/Token an einer hochschulinternen Infrastruktur, z.B. GWDG) ausgerichtet. GPT-5-Familie wird über diese Gateway-Schicht (Stand 2026) **nicht weitergereicht**. Eine direkte Anbindung an `api.openai.com` wäre möglich, erfordert aber Umbau (eigener API-Key, eigenes Billing, ggf. Datenschutz-Review für Hochschul-Compliance).

→ **Realistische produktive Optionen sind aktuell: `gpt-4.1-mini` (Cloud-OpenAI über B-API) oder ein Open-Source-Mini-Modell aus dem GWDG-Stack** (LLaMA-/Mistral-/Qwen-Familie auf hochschuleigener GPU-Hardware, derzeit nicht eval-vermessen).

### 2.2 Token-Volumen pro Monat

Aus den Eval-Daten hochgerechnet auf 60.000 Turns:

| Token-Typ | Volumen/Monat |
|---|---:|
| Input (uncached) | 549 M |
| Input (cached) | 1.424 M |
| Output (Completion) | 23 M |

### 2.3 OpenAI-Preise (Stand 2026)

| Modell | Input/M | Cached/M | Output/M |
|---|---:|---:|---:|
| **gpt-4.1-mini** | $0,40 | $0,10 | $1,60 |
| gpt-5-mini | $0,25 | $0,025 | $2,00 |
| gpt-5.4-mini | $0,75 | $0,075 | $4,50 |

### 2.4 Modellvergleich — Kosten/Monat

| Komponente | **gpt-4.1-mini** | gpt-5-mini | gpt-5.4-mini |
|---|---:|---:|---:|
| Input uncached (549 M × Preis) | $ 219,60 | $ 137,25 | $ 411,75 |
| Input cached (1.424 M × Preis) | $ 142,40 | $ 35,60 | $ 106,80 |
| Output (23 M × Preis) | $ 36,80 | $ 46,00 | $ 103,50 |
| **Summe USD/Monat** | **$ 398,80** | $ 218,85 | $ 622,05 |
| **Summe EUR/Monat** (Kurs ~0,93) | **≈ € 371** | ≈ € 204 | ≈ € 578 |
| Pro Chat-Session (4 Turns) | € 0,025 | € 0,014 | € 0,039 |
| Pro Turn | € 0,0062 | € 0,0034 | € 0,0096 |
| **Eval-Score** | **80 %** | 72 % | 84 % |
| **€/Score-Punkt** (€/Score) | **4,64** | 2,83 | 6,88 |
| **Verfügbarkeit B-API** | ✅ | ❌ | ❌ |

### 2.5 Empfehlung — gpt-4.1-mini

`gpt-4.1-mini` ist der **Sweet-Spot** in der Quality-Cost-Matrix:

- **Quality:** 80 % — nur 4 Punkte unter dem Spitzenmodell (5.4-mini), aber bereits ausreichend für produktive Nutzung.
- **Kosten:** € 371/Mo — **−36 % gegenüber gpt-5.4-mini** (€ 207/Monat Ersparnis).
- **Verfügbarkeit:** über die B-API direkt einsetzbar, kein Architektur-Umbau nötig.

`gpt-5-mini` wirkt rein nach Token-Preis attraktiv, hat aber:
- **−8 Punkte Quality** (72 % vs. 80 %) → 1 von 12 Klassifikations-/Antwort-Entscheidungen liegt zusätzlich daneben — fühlt sich für End-User direkt schlechter an.
- **Nicht über B-API erreichbar** → Architektur-Umbau wäre nötig.

`gpt-5.4-mini` (aktueller Stand) ist hochwertig, aber:
- **+57 % teurer** als gpt-4.1-mini.
- **Nicht über B-API erreichbar** → derzeit nur in der Direkt-OpenAI-Konfiguration.

→ **Wechsel-Empfehlung: gpt-5.4-mini → gpt-4.1-mini.** Spart **€ 207/Monat (≈ € 2.484/Jahr)** bei nur −4 Punkten Quality, plus die produktive Anbindung über die B-API.

### 2.6 Embeddings (text-embedding-3-small)

Wird bei jedem Turn für die Query-Embedding-Berechnung genutzt (RAG-Vektor-Suche):
- Pro Turn ~100 Tokens · 60.000 Turns/Monat · $0,02/M → **≈ $0,12/Monat** (vernachlässigbar)

### 2.7 Speech (TTS/STT, optional)

Mikrofon- und Vorlesefunktion sind im Widget abschaltbar (`show-language-buttons="false"`). Wenn aktiv, geschätzt 5 % der User × 30 s/Anfrage:
- Whisper STT $0,006/min · ~12,5 min/Tag → ~$2,25/Monat
- TTS $15/M Zeichen · ~3 M Zeichen/Monat → ~$45/Monat
- **Mit Speech aktiviert: zusätzlich ≈ € 45/Monat** (deaktivierbar)

---

## 3. Fixe Kosten — Infrastruktur

### 3.1 Hosting (vserver)

Der Chatbot läuft als Docker-Compose-Stack mit drei Containern (Backend, Studio, Chatbot/Caddy). Speicher- und CPU-Bedarf hängt vom Concurrent-Load ab.

#### Szenario A: bis 50 gleichzeitige Nutzer (Spitzenlast)

| Komponente | Empfehlung | Hetzner-Beispiel | €/Monat (netto) |
|---|---|---|---:|
| **vserver** | 4 vCPU shared, 8 GB RAM, 80 GB SSD | CX42 / CPX31 | **€ 8 – 10** |
| **Backups** (täglich, 7 Tage Rolling) | +20 % auf vserver | Hetzner-Backup | **€ 2 – 3** |
| **Domain** | .de oder .org | INWX, Hetzner | **€ 1** |
| **TLS-Zertifikat** | kostenlos (Let's Encrypt via Caddy) | — | **€ 0** |
| **Monitoring** | Uptime-Robot kostenlos / Better Uptime | — | **€ 0 – 5** |
| **Summe Hosting A** | | | **€ 11 – 19** |

**Begründung 4 vCPU/8 GB:** der Backend-Container hält das LLM-Service-Modul + RAG-Embeddings (906 Chunks × 1.536-dim × 4 Byte ≈ 6 MB) + Reranker-ONNX (~135 MB) im RAM. Pro Concurrent-Anfrage werden 200–400 MB RAM kurzzeitig belegt (Embedding + Reranking). Bei 50 concurrent Users mit ~10 % gleichzeitig in einem Token-Roundtrip: ~5 × 400 MB = 2 GB Spitzenlast nur für Bot-Logic + 2 GB Image/OS/SQLite/RAG-Cache + Buffer → **8 GB ist solide**.

#### Szenario B: bis 200 gleichzeitige Nutzer

| Komponente | Empfehlung | Hetzner-Beispiel | €/Monat (netto) |
|---|---|---|---:|
| **vserver** | 8 vCPU dedicated, 32 GB RAM, 240 GB SSD | CCX33 (dedicated CPU) | **€ 49** |
| **Backups** | +20 % | | **€ 10** |
| **Domain** | | | **€ 1** |
| **TLS** | Let's Encrypt | | **€ 0** |
| **Monitoring** | Better Uptime / Self-hosted | | **€ 5 – 10** |
| **Optional: zweiter App-Server für HA + Loadbalancer** | wenn Ausfallsicherheit gefordert | + LB + zweiter CCX13 | **+ € 30** |
| **Summe Hosting B** | | | **€ 65 – 100** |

**Begründung dedicated CPU + 32 GB:** bei 200 concurrent Users mit 20 % gleichzeitig in Token-Calls = 40 parallele 400-MB-Workloads → 16 GB peak nur für Bot-Logic. Plus OS, RAG-Reranker, SQLite-Cache, Buffer → 32 GB sicher. Dedicated vCPU verhindert Noisy-Neighbor-Probleme bei Spike-Traffic.

**Hinweis:** OpenAI-Rate-Limits können bei Szenario B begrenzen. Tier-Upgrade auf Tier 3+ ist meist mit Usage-History automatisch (oberhalb $250 Lifetime-Spend) — sonst manuell beantragen.

#### Marktpreise im Vergleich

Anbieter für 4 vCPU / 8 GB RAM (Szenario A):
- **Hetzner CX42** ≈ € 8/Mo · DE/FI · sehr stabil, GDPR-konform
- **Netcup VPS 1000 G10s** ≈ € 11/Mo · DE · gute SLA
- **Contabo VPS S** ≈ € 5/Mo · DE · günstigster, aber CPU-Oversubscription
- **IONOS VPS L** ≈ € 8/Mo · DE · solide

Anbieter für 8 vCPU dedicated / 32 GB (Szenario B):
- **Hetzner CCX33** ≈ € 49/Mo · DE/FI · dedicated vCPU, beste Performance
- **Netcup RS 4000 G11s** ≈ € 30–40/Mo · DE
- **AWS / Azure / GCP** — meist 3–5× teurer, lohnt nur bei spezifischen Cloud-Services

### 3.2 Server-Support (1 Stunde pro Monat)

Routinemäßiger Server-Betrieb über die normale Wartung hinaus — Patches einspielen, Logs sichten, Health-Checks bewerten, Backup-Kontrolle:

| Posten | Stunden/Monat | Stundensatz | €/Monat |
|---|---:|---:|---:|
| Server-Support (Patches, Monitoring, Health-Checks) | **1 h** | € 90–120 | **€ 90 – 120** |

Dieser Posten ist **bewusst klein**: er deckt nur die wiederkehrende vserver-Pflege. Inhaltliche Bot-Pflege (RAG, Patterns, Eval) liegt in 3.3 (Wartung).

### 3.3 Wartung & Content-Pflege (Personal, in Stunden)

Der Bot ist nach der Inbetriebnahme weitgehend autonom — die Pattern-Engine, RAG-Pipeline und Routing-Rules laufen ohne manuelle Eingriffe. Laufende Wartung beschränkt sich auf das Minimum, weil Watchtower/CI Image-Updates automatisiert und das Studio inhaltliche Edits per Klick erlaubt.

| Tätigkeit | Stunden/Monat | Bemerkung |
|---|---:|---|
| Security-Patches, Image-Updates | 0 – 0,5 | Watchtower zieht automatisch; nur Audit |
| Bug-Fixes & Edge-Case-Anpassungen | 0 – 1 | Bei stabilem Betrieb selten |
| Content-Pflege (RAG-Quellen, Patterns) | 0,5 – 1,5 | Über Studio einfach, nur bei neuen Themen |
| Eval-Auswertung, Prompt-Tuning | 0 – 1 | 1× pro Quartal ausreichend bei stabilem Betrieb |
| **Summe** | **1 – 3 h/Mo** | |

**Stundenkosten** (typische Marktpreise DE für Fullstack/ML-Devs):
- Inhouse / Werkvertrag (Mid-Level): € 60–90 brutto
- Externer Dienstleister / Agentur: € 90–140 brutto
- Senior-Spezialist / Engineering-Lead: € 120–180 brutto

**Wartungskosten:**
- Mindestaufwand (1 h × € 90): **≈ € 90/Mo**
- Realistisch (2 h × € 100): **≈ € 200/Mo**
- Höher (3 h × € 120): **≈ € 360/Mo**

→ Bei stabilem Betrieb sind die Token-Kosten der **größere Fixkostenblock** als die Wartung. Anlauf-/Onboarding-Phasen mit Persona-Tuning, Pattern-Anpassung und Content-Sweeps sind separat zu kalkulieren (typisch 20–40 h einmalig).

### 3.4 Sonstige Fixkosten

- **B-API-/OpenAI-Account-Mindestumsatz**: kein Mindestumsatz; B-API meist über Hochschul-Vertrag pauschalisiert oder nutzungsabhängig
- **MCP-Server WLO** (`search_wlo_*`-Tools): hostet WLO selbst → keine externen Kosten
- **Studio API-Key**: keine Lizenzkosten (eigene Software)
- **TLS / Let's Encrypt**: kostenlos
- **CDN für Widget-Bundle**: nicht zwingend (Backend liefert direkt aus); optional Cloudflare-Free für Cache → € 0
- **Speech (TTS/STT)**: nur wenn aktiviert (siehe 2.7) → € 0–45/Mo

---

## 4. Gesamtkalkulation (mit gpt-4.1-mini)

### Szenario A — bis 50 concurrent (≈ 2.500 Tagesbesucher, 500 Chat-Sessions/Tag)

| Posten | Niedrig | Realistisch | Hoch |
|---|---:|---:|---:|
| **OpenAI Tokens** (gpt-4.1-mini) | € 371 | € 371 | € 371 |
| Embeddings | € 0 | € 0 | € 0 |
| Speech (optional) | € 0 | € 0 | € 45 |
| **Hosting + Backup + Domain** | € 11 | € 15 | € 19 |
| **Monitoring** | € 0 | € 5 | € 10 |
| **Server-Support** (1 h × € 90–120) | € 90 | € 100 | € 120 |
| **Wartung & Content-Pflege** (1–3 h × € 90–120) | € 90 | € 200 | € 360 |
| **Summe Szenario A** | **€ 562** | **€ 691** | **€ 925** |

### Szenario B — bis 200 concurrent (höhere Reichweite, ggf. 10.000+ Tagesbesucher)

Token-Kosten skalieren mit **Sessions, nicht concurrent users**. Bei 4× Volumen (240k Turns/Monat):

| Posten | Niedrig | Realistisch | Hoch |
|---|---:|---:|---:|
| **OpenAI Tokens** (gpt-4.1-mini, 4× Volumen) | € 1.484 | € 1.484 | € 1.484 |
| Embeddings | € 0 | € 1 | € 1 |
| Speech (optional) | € 0 | € 0 | € 180 |
| **Hosting + Backup + Domain** | € 60 | € 70 | € 100 |
| **Monitoring** | € 5 | € 10 | € 15 |
| **Server-Support** (1 h × € 90–120) | € 90 | € 100 | € 120 |
| **Wartung & Content-Pflege** (1–3 h × € 90–120) | € 90 | € 200 | € 360 |
| **Summe Szenario B** | **€ 1.729** | **€ 1.865** | **€ 2.260** |

### 4.3 Pro-Session-Kosten

| | Szenario A (15.000 Sessions/Mo) | Szenario B (60.000 Sessions/Mo) |
|---|---:|---:|
| Token-Kosten/Session (gpt-4.1-mini) | **€ 0,025** | **€ 0,025** |
| All-In/Session inkl. Hosting + Wartung + Support | **€ 0,046** | **€ 0,031** |

Pro **User-Anfrage** (Turn) bei gpt-4.1-mini: **€ 0,006** Token · **€ 0,012** Vollkosten (Szenario A).

→ **Token-Kosten dominieren jetzt die Bilanz** (54 % der Vollkosten in Szenario A, 80 % in Szenario B). Hosting + Wartung + Support zusammen nur ~ € 320/Mo bei gleichbleibender Volumen-Skalierung.

---

## 5. Empfehlungen & Hebel

### 5.1 Sofort-Hebel (keine Architektur-Änderung)

| Maßnahme | Ersparnis/Monat (Szenario A) | Aufwand |
|---|---:|---|
| **Wechsel gpt-5.4-mini → gpt-4.1-mini** | € 207 (–36 %) bei nur −4 Quality-Punkten | 1 ENV-Variable umstellen + Eval-Run zur Validierung |
| Speech standardmäßig aus (`show-language-buttons="false"`) | bis € 45 | Embed-Attribut |
| Cache-TTL erhöhen (Prompt-Cache) | 5–10 % | bereits gut, weiteres Tuning marginal |

### 5.2 Mittelfristige Hebel

- **MCP-Result-Caching**: search_wlo_topic_pages für identische Queries cachen → reduziert Tool-Calls um geschätzt 30 %
- **Pattern-Engine vereinfachen**: einige Patterns laufen auch bei eindeutigen Intent-Matches durch alle 3 Phasen — Bypass für `force_tool_use` + `direct_action` spart ~5 % Klassifikator-Kosten
- **Smaller Reranker**: aktuell 135 MB ONNX, könnte durch BAAI/bge-reranker-v2-m3 (ähnliche Qualität, 50 MB) ersetzt werden — RAM-Ersparnis 80 MB

### 5.3 Strategische Frage: Open-Source-LLM (GWDG)?

Bei 60.000+ Turns/Monat sind die OpenAI-Kosten ~ € 371/Mo. Ein selbst-gehostetes Mini-Modell auf GWDG-Hardware (LLaMA-3.1-8B, Qwen-2.5-7B oder Mistral-7B-Instruct) würde:
- Hardware: pauschaliert über GWDG-Konsortialvertrag — **wahrscheinlich keine Mehrkosten** für die Hochschule, weil GPU-Cluster ohnehin gehalten wird
- Lizenzkosten: € 0
- Quality: muss im integrierten Eval-Setup vermessen werden (für die OpenAI-Mini-Modelle bekannt: 72–84 %, vergleichbare Open-Source-Modelle landen erfahrungsgemäß bei 60–78 %)

→ **Lohnt sich, sobald die GWDG-Infrastruktur als kostenneutral verbucht werden kann.** Eval auf der GWDG-Variante ist vor einer Entscheidung Pflicht — die Quality kann je nach Modell 5–15 Punkte unter gpt-4.1-mini liegen.

---

## 6. Annahme-Sensitivitäten (was wenn die Rechnung nicht passt?)

| Wenn… | Auswirkung |
|---|---|
| Nur 10 % Chat-Adoption (statt 20 %) | Token-Kosten halbieren sich → € 186/Mo statt € 371 |
| Sessions 8 Turns lang (statt 4) | Token-Kosten verdoppeln sich → € 742/Mo |
| Cache-Hit-Rate fällt auf 50 % | Token-Kosten +20 % → € 445/Mo (Cache funktioniert i.d.R. stabil) |
| 5.000 Tagesbesucher (statt 2.500) | Linear: alle Token-Posten verdoppeln |
| Wartung steigt auf 5 h/Mo (z.B. neue Themen, Persona-Anpassung) | + € 200/Mo zusätzlich |
| Open-Source-LLM via GWDG (kostenneutral) | Token-Kosten ~ € 0 statt € 371 — bei ggf. niedrigerer Quality |

---

## 7. Zusammenfassung — Entscheidungs-TL;DR

| Frage | Antwort |
|---|---|
| **Welches Modell?** | **gpt-4.1-mini** — beste B-API-verfügbare Quality-Cost-Balance (80 % Eval-Score, € 371/Mo) |
| **Welcher Server?** | bis 50 concurrent: **Hetzner CX42 (€ 8/Mo)**; bis 200: **CCX33 (€ 49/Mo)** |
| **Was kostet's monatlich (50 concurrent, realistisch)?** | **≈ € 691/Mo** Vollkosten · davon Tokens € 371, Wartung € 200, Server-Support € 100, Hosting € 20 |
| **Was kostet 1 Chat-Anfrage des Users?** | **€ 0,006 reine Token-Kosten · € 0,012 Vollkosten** (Szenario A) |
| **Größter Sparhebel?** | Modellwechsel `gpt-5.4-mini` → `gpt-4.1-mini`: **−36 % bei den Token-Kosten, nur −4 Punkte Quality**, plus B-API-Verfügbarkeit |
| **Strategische Option?** | Open-Source-LLM auf GWDG-Infrastruktur — Eval erforderlich, potentiell quasi kostenneutral |

---

## Quellen

- OpenAI-Preise (Mai 2026):
  - [OpenAI API Pricing — offizielle Seite](https://openai.com/api/pricing/)
  - [GPT-4.1 / GPT-5 Pricing Overview, costbench.com](https://costbench.com/software/llm-api-providers/openai-api/)
  - [GPT-5.4 Mini Pricing, pricepertoken.com](https://pricepertoken.com/pricing-page/model/openai-gpt-5.4-mini)
  - [text-embedding-3-small Pricing, helicone.ai](https://www.helicone.ai/llm-cost/provider/openai/model/text-embedding-3-small)
- Hosting-Marktpreise:
  - [Hetzner Cloud — regular performance](https://www.hetzner.com/cloud/regular-performance)
  - [Hetzner Cloud — dedicated vCPU (CCX)](https://www.hetzner.com/cloud/general-purpose)
  - [Netcup VPS](https://www.bestvpsproviders.com/providers/netcup)
  - [Europe VPS Pricing 2026 — Hostadvice](https://hostadvice.com/blog/web-hosting/vps/europe-vps-pricing/)
- Token-Verbrauchsdaten: 5 Selbst-Eval-Runs (eval_runs in `backend/badboerdi.db`, 720 Turns aggregiert)
- Quality-Scores: integrierte Selbstevaluation des Chatbots (LLM-as-Judge auf Persona/Intent/Pattern-Klassifikation + Antwortqualität)
