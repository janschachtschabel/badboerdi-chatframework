"""Run the BadBoerdi backend server."""
import os
import uvicorn

if __name__ == "__main__":
    # reload kann per ENV deaktiviert werden (z.B. Colab, Docker).
    # Default an fuer lokale Entwicklung; Colab setzt BOERDI_UVICORN_RELOAD=0,
    # damit der File-Watcher in der VM keine Probleme macht.
    reload = os.getenv("BOERDI_UVICORN_RELOAD", "1").lower() not in ("0", "false", "no")
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=reload)
