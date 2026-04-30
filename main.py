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
IMAP_POLL_INTERVAL = int(os.environ.get("IMAP_POLL_INTERVAL", "34200")) # Revisa casilla cada 12h
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
# Pipeline de procesamiento (2 etapas en 2 threads):
#   1) extraer_datos_archivo  ->  lee el adjunto y arma un dict con los datos
#   2) formatear_y_enviar     ->  transforma al formato destino y reenvía
# Las etapas se encadenan con add_done_callback: cuando termina la 1,
# se dispara la 2 en otro thread del executor.
# ============================================================
def extraer_datos_archivo(email_data):
    
    """Etapa 1: levanta el adjunto (xlsx/csv) y devuelve los datos extraídos.

    Retorna un dict con la info que necesita la etapa 2, o None si no hay
    nada que procesar. Lo que retorne acá llega tal cual a `formatear_y_enviar`.
    """
    try:
        print(f"📧 Email recibido | from={email_data['from']} | subject={email_data['subject']!r}")

        # 1) Buscar el adjunto que nos interesa (Excel o CSV)
        asn_data = None
        for att in email_data["attachments"]:
            nombre = (att["filename"] or "").lower()
            if nombre.endswith((".xlsx", ".xls", ".csv")):
                asn_data = att
                break

        if not asn_data:
            print("⚠️  No hay adjunto xlsx/xls/csv; nada que procesar")
            return None

        service.mintsoft_asn_processing(asn_data)

        # Armamos el dict que recibe la etapa 2. Es el contrato entre
        # extraer_datos_archivo() y formatear_y_enviar().
        datos_extraidos = {
            "email_uid": email_data["uid"],
            "remitente": email_data["from"],
            "filename": asn_data["filename"],
            "raw_bytes": asn_data["content"],
        }

        print(f"✅ Etapa 1 OK | archivo={asn_data['filename']}")
        return datos_extraidos

    except Exception as e:
        print(f"❌ Error en etapa 1 (extracción): {e}")
        return None


def formatear_y_enviar(datos_extraidos):
    """Etapa 2: arma el archivo en el formato destino y lo reenvía por mail."""
    try:
        print(f"🛠  Etapa 2 iniciada | uid={datos_extraidos['email_uid']}")

        # ------------------------------------------------------
        # TODO: transformar `datos_extraidos["filas"]` al formato deseado
        #   filas_destino = transformar(datos_extraidos["filas"])
        #   archivo_salida = generar_xlsx(filas_destino)   # o csv/json/etc
        # ------------------------------------------------------

        # ------------------------------------------------------
        # TODO: reenviar por mail (cuando definas el destinatario/canal)
        #   enviar_mail(
        #       destinatario="...",
        #       asunto="...",
        #       cuerpo="...",
        #       adjunto=archivo_salida,
        #       filename="resultado.xlsx",
        #   )
        # ------------------------------------------------------

        print("✅ Etapa 2 OK | archivo formateado y reenviado")

    except Exception as e:
        print(f"❌ Error en etapa 2 (formateo/envío): {e}")


def _on_extraccion_completa(future):
    """Callback que dispara la etapa 2 cuando termina la etapa 1.

    Se ejecuta en el mismo thread que terminó la etapa 1, así que solo
    re-submitea al executor para que la etapa 2 corra en otro thread.
    """
    try:
        datos_extraidos = future.result()
        if datos_extraidos is None:
            return  # nada que formatear
        executor.submit(formatear_y_enviar, datos_extraidos)
    except Exception as e:
        print(f"❌ Error encadenando etapas: {e}")


# ============================================================
# Listener IMAP en background (mismo patrón que tu webhook:
# trabajo pesado en threads, dispatch rápido)
# ============================================================
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

            # Tu lógica solo procesa mails con adjunto xlsx/xls/csv;
            # si no tiene, también lo ignoramos sin ruido.
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
            # Etapa 1 en un thread; al terminar, el callback dispara la
            # etapa 2 en otro thread del mismo executor.
            future = executor.submit(extraer_datos_archivo, email_data)
            future.add_done_callback(_on_extraccion_completa)


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
