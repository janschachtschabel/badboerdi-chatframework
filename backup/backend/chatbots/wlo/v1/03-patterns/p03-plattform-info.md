# P3 Plattform-Info — GEMERGED in p03-wissens-frage.md (Welle E Sprint 3, 2026-05-18)

P3 (Plattform-Info) und P4 (Konzept-Info) wurden zu einem gemeinsamen
Pattern **„Wissens-Frage" (id: P3)** zusammengeführt — siehe
`p03-wissens-frage.md`.

**Hintergrund**: Im ersten Welle-E-Eval-Run (eval-e6305d995db0) drifteten
sehr viele Intents zu INT-PLATTFORM/P3, weil P3 und P4 semantisch zu nah
und vom LLM-Classifier nicht zuverlässig trennbar waren. Beide nutzten
`sources: ["rag"]` mit unterschiedlichen `rag_areas`. Der Merge lädt
jetzt alle 7 RAG-Bereiche (Plattform + Konzepte) im Kombi-Kontext; der
LLM antwortet inhaltlich aus dem passenden Bereich.

Diese Datei bleibt nur als Marker und wird vom Loader übersprungen
(kein `id:`-Frontmatter mehr).
