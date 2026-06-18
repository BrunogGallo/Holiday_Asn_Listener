from flask import Flask, jsonify
import os
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from imap_tools import MailBox, AND
from services.asn_service import MintsoftAsnService

app = Flask(__name__)

# ============================================================
# Variables de entorno
# ============================================================
IMAP_HOST = os.environ.get("IMAP_HOST", "imap.gmail.com")
IMAP_PORT = int(os.environ.get("IMAP_PORT", "993"))
IMAP_USERNAME = os.environ.get("IMAP_USERNAME")
IMAP_PASSWORD = os.environ.get("IMAP_PASSWORD")
IMAP_FOLDER = os.environ.get("IMAP_FOLDER", "INBOX")
IMAP_POLL_INTERVAL = int(os.environ.get("IMAP_POLL_INTERVAL", "34200"))  # Revisa casilla cada 12h
IMAP_FROM_FILTER = os.environ.get("IMAP_FROM_FILTER")        # opcional
IMAP_SUBJECT_FILTER = os.environ.get("IMAP_SUBJECT_FILTER")  # opcional

executor = ThreadPoolExecutor(max_workers=10)
service = MintsoftAsnService()

# UIDs ya procesados en esta corrida del proceso. Es una red de seguridad
# por si IMAP/imap-tools devuelve el mismo mensaje dos veces. Como
# mark_seen=True el dedupe principal lo hace el server; esto cubre el
# caso del mismo fetch yieldando dos veces el mismo UID.
PROCESSED_UIDS: set[str] = set()


# ============================================================
# Procesamiento del adjunto.
# Cada email matcheado se procesa en un thread del executor para no
# bloquear el loop IMAP. Toda la lógica (cargar a Mintsoft, generar el
# template Xoro y enviarlo por mail) vive en MintsoftAsnService.
# ============================================================
def procesar_email(email_data):
    """Levanta el adjunto (xlsx/csv) y lo manda a procesar al service."""
    try:
        print(f"📧 Email recibido | from={email_data['from']} | subject={email_data['subject']!r}")

        # Buscar el adjunto que nos interesa (Excel o CSV)
        asn_data = None
        for att in email_data["attachments"]:
            nombre = (att["filename"] or "").lower()
            if nombre.endswith((".xlsx", ".xls", ".csv")):
                asn_data = att
                break

        if not asn_data:
            print("⚠️  No hay adjunto xlsx/xls/csv; nada que procesar")
            return

        service.mintsoft_asn_processing(asn_data)
        print(f"✅ Procesado OK | archivo={asn_data['filename']}")

    except Exception as e:
        print(f"❌ Error procesando email: {e}")


def chequear_emails():
    """Se conecta a la casilla, lee no leídos y dispara procesar_email."""
    if not (IMAP_USERNAME and IMAP_PASSWORD):
        print("⚠️  Faltan IMAP_USERNAME / IMAP_PASSWORD; salteo el ciclo")
        return

    # Filtros opcionales
    criteria_kwargs = {"seen": False}
    if IMAP_FROM_FILTER:
        criteria_kwargs["from_"] = IMAP_FROM_FILTER
    if IMAP_SUBJECT_FILTER:
        criteria_kwargs["subject"] = IMAP_SUBJECT_FILTER

    with MailBox(IMAP_HOST, port=IMAP_PORT).login(
        IMAP_USERNAME, IMAP_PASSWORD, initial_folder=IMAP_FOLDER
    ) as mailbox:
        for msg in mailbox.fetch(AND(**criteria_kwargs), mark_seen=True, bulk=True):
            subject = (msg.subject or "").strip()

            # Dedupe por UID (red de seguridad por si IMAP yieldea dos veces).
            if msg.uid and msg.uid in PROCESSED_UIDS:
                continue
            if msg.uid:
                PROCESSED_UIDS.add(msg.uid)

            # Workspace genera copias internas (scanners DLP, auditoría, etc.)
            # que llegan al INBOX con headers vacíos. Las ignoramos en silencio.
            if not msg.from_ or not subject:
                continue

            # Solo procesamos mails con adjunto xlsx/xls/csv; si no tiene,
            # lo ignoramos sin ruido.
            if not any(
                (a.filename or "").lower().endswith((".xlsx", ".xls", ".csv"))
                for a in msg.attachments
            ):
                continue

            # Match exacto del subject (IMAP SUBJECT hace substring,
            # acá garantizamos coincidencia exacta).
            if IMAP_SUBJECT_FILTER and subject != IMAP_SUBJECT_FILTER:
                continue

            email_data = {
                "uid": msg.uid,
                "from": msg.from_,
                "to": list(msg.to),
                "subject": subject,
                "text": msg.text or "",
                "html": msg.html or None,
                "attachments": [
                    {
                        "filename": a.filename,
                        "content_type": a.content_type,
                        "content": a.payload,
                    }
                    for a in msg.attachments
                ],
            }
            # Procesamos en un thread del executor para no bloquear el loop.
            executor.submit(procesar_email, email_data)


def loop_imap():
    """Thread de fondo: chequea cada IMAP_POLL_INTERVAL segundos."""
    print(f"🔄 Listener IMAP iniciado | host={IMAP_HOST} | user={IMAP_USERNAME} | cada {IMAP_POLL_INTERVAL}s")
    while True:
        try:
            chequear_emails()
        except Exception as e:
            print(f"❌ Error en ciclo IMAP: {e}")
        time.sleep(IMAP_POLL_INTERVAL)


# ============================================================
# Endpoints HTTP
# ============================================================
@app.route("/", methods=["GET"])
def root():
    return jsonify({"service": "email-listener", "status": "ok"}), 200


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


# ============================================================
# Arranque
# ============================================================
# Lanzamos el listener IMAP al importar el módulo (lo hace Gunicorn/Railway).
# daemon=True para que muera junto al proceso.
threading.Thread(target=loop_imap, daemon=True).start()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)