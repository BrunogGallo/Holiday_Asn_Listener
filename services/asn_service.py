import sys
import os
import io
import json
import csv
import smtplib
from email.message import EmailMessage
from pathlib import Path
import pandas as pd
from datetime import datetime, timedelta
from clients.mintsoftClient import MintsoftAsnClient


# Esto obtiene la ruta de la carpeta "XorosoftMintsoft" (la raiz)
root_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

# Agregamos la raiz al buscador de Python
if root_path not in sys.path:
    sys.path.append(root_path)


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

FMT = "%m/%d/%Y %I:%M:%S %p"

# --- Xoro template constants ------------------------------------------------
XORO_LOCATION_NAME = "USA WAREHOUSE"
XORO_CSV_COLUMNS = [
    "StoreName",
    "AsnNumber",
    "PONumber",
    "ItemNumber",
    "QtyToReceive",
    "LocationName",
    "ThirdPartyRefNo",
    "ThirdPartySource",
    "RefNumber"
]

# --- SMTP / email config ----------------------------------------------------
# Set these as environment variables so credentials aren't committed to the repo.
SMTP_HOST     = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT     = int(os.getenv("SMTP_PORT", "465"))
SMTP_USER     = os.getenv("SMTP_USER")          # e.g. "ops@the5411.com"
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")      # Gmail app password or SMTP password
SMTP_FROM     = os.getenv("SMTP_FROM", SMTP_USER)
XORO_EMAIL_TO = os.getenv("XORO_EMAIL_TO", "bgallo@the5411.com")


class MintsoftAsnService:

    def __init__(self):
        self.client = MintsoftAsnClient()


    def create_cartons(self, asn_cartons):
        for carton in asn_cartons:
            carton_data = {
                "WarehouseId": 3,
                "StorageMediaName": "Stock",
                "Code": carton,
                "LocationId": 7,
            }
            print(f"Creando la caja - {carton}")
            self.client.create_carton(carton_data)
        return None


    def mintsoft_asn_processing(self, attachment):

        # Extraigo bytes del file
        content = attachment["content"]
        file_name = attachment["filename"].lower()

        # Pasamos el archivo a un formato manejable
        if file_name.endswith((".xlsx", ".xls")):
            df = pd.read_excel(io.BytesIO(content), engine="openpyxl")
        elif file_name.endswith(".csv"):
            df = pd.read_csv(io.BytesIO(content), encoding="utf-8")
        else:
            raise ValueError(f"Tipo de archivo no soportado: {file_name}")

        po_number = df.iloc[1, 0] #2da fila, 1er columna
        asn_number = df.iloc[1, 1] #2da fila, 2da columna
        carton_amount = df.iloc[:, 5].nunique()

        carton_per_sku = (
            df.groupby(df.columns[2])[df.columns[5]]
            .apply(lambda s: ",".join(sorted(set(s.astype(str)))))
            .to_dict()
        )

        # qty_per_sku = df.groupby(df.columns[2])[df.columns[6]].sum().reset_index()
        # qty_per_sku.columns = ["SKU", "Quantity"]
        # asn_items = qty_per_sku.to_dict(orient="records")

        qty_per_sku_per_carton = df.groupby([df.columns[2], df.columns[5]])[df.columns[6]].sum().reset_index()
        qty_per_sku_per_carton.columns = ["SKU", "Quantity"]

        # Lista de { "SKU": ..., "Quantity": ... }
        asn_items = qty_per_sku_per_carton.to_dict(orient="records")

        # Crear las cajas con formato: asn_number - numero de caja
        asn_cartons = [f"{asn_number}-{i}" for i in range(1, carton_amount + 1)]

        # Comparacion para ver si ese ASN ya esta cargado en Mintsoft
        current_mint_asns = self.client.get_asns()
        asn_exists = any(
            item.get("POReference") == asn_number for item in current_mint_asns
        )

        if asn_exists:
            print("ASN ya cargado en Mintsoft")
            return None

        print("ASN no existe en Mintsoft, cargando informacion...")

        print("Creando cajas")
        self.create_cartons(asn_cartons)

        print(f"Creando ASN - {asn_number}")
        mintsoft_payload = {
            "WarehouseId": 3,                       # General / Wholesale
            "POReference": asn_number,              # AsnNumber
            "Supplier": "XoroSoft Migration",
            "EstimatedDelivery": "",
            "GoodsInType": "Carton",
            "Quantity": len(asn_cartons),
            "ClientId": 4,                          # 4 para Holiday Company
            "Comments": ", ".join(asn_cartons),
            "Items": asn_items,
        }
        self.client.create_asn(mintsoft_payload)

        # --- Generar CSV de Xoro y enviarlo por mail ---
        xoro_template_info = {
            "asn_number": asn_number,
            "po_number": po_number,
            "asn_items": asn_items,
            "carton_per_sku": carton_per_sku
        }
        csv_path = self.prepare_xoro_asn_template(xoro_template_info)
        self.send_xoro_csv_email(csv_path, asn_number, recipient=XORO_EMAIL_TO)

        return None


    def prepare_xoro_asn_template(self, data, output_dir="xoro_templates"):
        asn_number = data["asn_number"]
        po_number = data["po_number"]
        carton_per_sku = data["carton_per_sku"]
        items = data["asn_items"]

        if not items:
            raise ValueError(
                f"No items provided for ASN {asn_number}; cannot build Xoro template."
            )

        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"xoro_asn_{asn_number}.csv"

        with output_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=XORO_CSV_COLUMNS)
            writer.writeheader()

            if asn_number.startswith("TST"):
                store_name = "Test Store"
                location_name = "TEST"
            elif asn_number.startswith("USA"):
                store_name = "USA Warehouse"
                location_name = "USA WAREHOUSE"
            else:
                store_name = "Drop Ship"
                location_name = "NS01"
        
            for item in items:
                writer.writerow({
                    "StoreName": store_name,
                    "AsnNumber": asn_number,
                    "PONumber": po_number,
                    "ItemNumber": item["SKU"],
                    "QtyToReceive": item["Quantity"],
                    "LocationName": location_name,
                    "ThirdPartyRefNo": asn_number,
                    "ThirdPartySource": "Mintsoft",
                    "RefNumber": f"{asn_number}-{carton_per_sku[item['SKU']]}"
                })

        print(f"Xoro ASN template generated: {output_path}")
        return output_path


    def send_xoro_csv_email(self, csv_path, asn_number, recipient):
        if not SMTP_USER or not SMTP_PASSWORD:
            raise RuntimeError(
                "SMTP_USER / SMTP_PASSWORD env vars are not set; cannot send email."
            )

        csv_path = Path(csv_path)

        msg = EmailMessage()
        msg["Subject"] = f"Xoro ASN Template - {asn_number}"
        msg["From"]    = SMTP_FROM
        msg["To"]      = recipient
        msg.set_content(
            f"Adjunto el template Xoro para el ASN {asn_number}.\n"
            f"Por favor, subirlo manualmente al WMS Xoro."
        )

        with csv_path.open("rb") as f:
            msg.add_attachment(
                f.read(),
                maintype="text",
                subtype="csv",
                filename=csv_path.name,
            )

        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as smtp:
            smtp.login(SMTP_USER, SMTP_PASSWORD)
            smtp.send_message(msg)

        print(f"Xoro ASN CSV emailed to {recipient}")