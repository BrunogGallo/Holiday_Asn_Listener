# Email Listener (Flask + Railway)

App mínima en Flask que poolea una casilla de email cada N segundos y dispara
una función `procesar_email` por cada mail nuevo. Mismo patrón que un webhook
clásico, pero el "trigger" es la llegada del email en vez de un POST HTTP.

## Estructura

```
.
├── main.py             # ⬅️  todo está acá
├── requirements.txt
├── Procfile
└── .env.example
```

## Cómo funciona

1. Al arrancar, `main.py` lanza un **thread de fondo** (`loop_imap`) que cada
   `IMAP_POLL_INTERVAL` segundos se conecta a la casilla y trae los mails no leídos.
2. Por cada mail, dispara `executor.submit(procesar_email, email_data)` —
   exactamente el mismo patrón que tenés en tu webhook de Mintsoft.
3. Tu lógica vive en `procesar_email(email_data)` dentro de `main.py`.

## Correr en local

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env       # editá con tus credenciales
export $(cat .env | xargs)  # carga las vars
python main.py
```

Si querés, podés usar `python-dotenv` y agregar `from dotenv import load_dotenv; load_dotenv()` arriba del todo.

## Deploy a Railway

1. Subí el repo a GitHub.
2. En Railway: **New Project → Deploy from GitHub repo**.
3. En **Variables**, cargá las del `.env.example`:
   - `IMAP_HOST`, `IMAP_PORT`, `IMAP_USERNAME`, `IMAP_PASSWORD`
   - `IMAP_POLL_INTERVAL` (opcional, default 30)
   - `IMAP_FROM_FILTER`, `IMAP_SUBJECT_FILTER` (opcionales)
4. Railway detecta `Procfile` y arranca con Gunicorn.

> ⚠️ Importante: el Procfile usa `--workers 1` a propósito. Con varios workers,
> cada uno arrancaría su propio thread IMAP y procesarías los emails N veces.
> Para escalar, usá `--threads` (no `--workers`) o separá el poller a otro
> servicio.

## Gmail: cómo obtener el password

1. Activá 2-Step Verification.
2. Generá un App Password en https://myaccount.google.com/apppasswords.
3. Usalo como `IMAP_PASSWORD`.

## Filtros

Si solo te interesan ciertos mails:

```env
IMAP_FROM_FILTER=facturas@proveedor.com
IMAP_SUBJECT_FILTER=Nueva orden
```

## Tu lógica

Editá `procesar_email` en `main.py`. Recibís un dict con `from`, `to`, `subject`,
`text`, `html`, `attachments` (lista con `filename`, `content_type`, `content`)
y `uid`.
