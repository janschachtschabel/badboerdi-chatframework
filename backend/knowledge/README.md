# Knowledge-Verzeichnis — Seeds und Factory-Snapshot

Dieser Ordner enthält die "as-shipped" Inhalte, die bei einer komplett
leeren Datenbank automatisch eingespielt werden. Zwei Varianten, eine
klare Präferenz:

| Datei | Inhalt | Status | Enthält |
|---|---|---|---|
| `factory-snapshot.zip` | **Primär** — vollständiger Factory-Zustand | **Empfohlen** | Komplette `chatbots/wlo/v1/`-Config + SQLite-DB inkl. RAG-Chunks **mit Embeddings** und Studio-Einstellungen. Keine Sessions / Memory / Logs. |
| `rag-seed.json` | Legacy-Fallback (nur RAG-Chunks) | Optional | Nur RAG-Chunks **ohne Embeddings** (Embeddings werden beim Start regeneriert). Wird nur genutzt, wenn `factory-snapshot.zip` fehlt. |
| `sources/` | Menschenlesbare Quelltexte (Markdown) | Dokumentation | Siehe `sources/README.md` — Quelle der Wahrheit für zukünftige Seed-Regenerationen |

## Verhalten beim Start

`database.init_db()` → `database._restore_factory_snapshot_if_empty()`:

1. Wenn DB **nicht leer** (rag_chunks / sessions / messages >0) → überspringen.
2. Wenn bereits ein Marker `factory_version` mit aktuellem Datei-Mtime
   in der `meta`-Tabelle steht → überspringen.
3. Sonst: `factory-snapshot.zip` entpacken, Config-Tree ersetzen, DB über
   SQLite-Backup-API replicieren, Embeddings sind **sofort** nutzbar.

Kommt Schritt 3 nicht durch (Datei fehlt/defekt) → Fallback auf
`_import_rag_seed_if_empty()` mit `rag-seed.json` (nur RAG, Embeddings
werden async post-start berechnet).

## Factory pflegen

### Im Studio (empfohlen)

1. **Snapshots-Modal** öffnen (📸 im Header)
2. Variante A — aus vorhandenem User-Snapshot:
   - Bei einer Zeile in der Snapshot-Liste auf **🏭 Als Factory** klicken.
   - Der ZIP wird 1:1 nach `knowledge/factory-snapshot.zip` kopiert.
3. Variante B — aus dem Live-Zustand:
   - Im **Werkseinstellungen**-Block (gelb markiert) auf **⇲ Live sichern**
     klicken.
   - Erstellt frischen Snapshot aus aktueller Config + DB und ersetzt
     damit die Factory.

### Via API

```bash
# User-Snapshot zum Factory promoten
curl -X POST "http://localhost:8000/api/config/factory/save?from_snapshot=snap-…"

# Live-Zustand → Factory
curl -X POST "http://localhost:8000/api/config/factory/save"

# Aktuellen Factory-Snapshot herunterladen
curl -o factory.zip "http://localhost:8000/api/config/factory/download"

# ZIP direkt hochladen (Ops)
curl -X POST -F "file=@factory.zip" "http://localhost:8000/api/config/factory/upload"
```

### Per Hand

Eine ZIP mit der Struktur

```
config/
  01-base/…
  02-domain/…
  …
db/
  badboerdi.db
```

als `backend/knowledge/factory-snapshot.zip` ablegen. Beim nächsten
Start mit leerer DB greift sie automatisch.

## Factory wiederherstellen

### Im Studio

📸 **Snapshots** → Werkseinstellungen-Block → **↺ Zurücksetzen**.
Fragt 2× nach und überschreibt Config + DB (`wipe=true, include_db=true`).

### Via API

```bash
curl -X POST "http://localhost:8000/api/config/factory/restore?wipe=true&include_db=true"
```

## Unterschied zu User-Snapshots

| | **Factory** | **User-Snapshot** |
|---|---|---|
| Pfad | `knowledge/factory-snapshot.zip` | `snapshots/snap-YYYYMMDD-….zip` |
| Anzahl | genau 1 | beliebig viele |
| Auto-Restore bei leerer DB | **ja** | nein |
| Git-committed? | **ja** (Versionierung des Default-States) | nein (lokaler Arbeits-Snapshot) |
| Im Studio sichtbar | gelber Block „Werkseinstellungen" | normale Liste |
| Löschbar im Studio | nein | ja (🗑-Button) |

## rag-seed.json (Legacy)

Die bestehende `rag-seed.json` bleibt als Fallback im Repo. Sie wird
**nur** genutzt, wenn `factory-snapshot.zip` fehlt. Für Updates nutze
das Skript:

```bash
python -m scripts.rag_export --version 2026-04-22
```

Das zieht Chunks aus der lokalen DB und schreibt sie ohne Embeddings
zurück in `knowledge/rag-seed.json`. Gut, um die RAG-Grundlage in Git
diff-bar zu halten, aber **nicht** für Embeddings-Pflege.
