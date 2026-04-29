import sys
import os
import io
import json
import pandas as pd
from datetime import datetime, timedelta
from clients.mintsoftClient import MintsoftAsnClient


# Esto obtiene la ruta de la carpeta "XorosoftMintsoft" (la raíz)
root_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

# Agregamos la raíz al buscador de Python
if root_path not in sys.path:
    sys.path.append(root_path)



ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

FMT = "%m/%d/%Y %I:%M:%S %p"

class MintsoftAsnService:

    def __init__(self):
        self.mint_o = MintsoftAsnClient()

    def check_against_current_asns(self, asn_data):
        # Extraigo bytes del file
        content = asn_data["content"]
        file_name = asn_data["filename"].lower()

        # Pasamos el archivo a un formato manejable
        if file_name.endswith((".xlsx", ".xls")):
            df = pd.read_excel(io.BytesIO(content), engine='openpyxl')
        
        elif file_name.endswith(".csv"):
            # Para CSV, a veces necesitas especificar el encoding
            df = pd.read_csv(io.BytesIO(content), encoding='utf-8')        

        po_number = df.iloc[1, 0]
        asn_number = df.iloc[2, 1]
        carton_amount = df.iloc[:, 5].nunique()

        qty_per_sku = df.groupby(df.columns[2])[df.columns[6]].sum().reset_index()
        qty_per_sku.columns = ["SKU", "Quantity"]

        # Convertir a diccionario { SKU: Cantidad }
        sku_dict = qty_per_sku.to_dict(orient='records')

        asn_cartons = []

        # Crear las cajas con formato: asn_number - numero de caja
        for i in range(1, carton_amount + 1):
            asn_cartons.append(f"{asn_number}-{i}")

        asn_items = []

        for sku in sku_dict:
            asn_items.append(sku)

        print(po_number)
        print(asn_number)
        print(asn_cartons)
        print(asn_items)