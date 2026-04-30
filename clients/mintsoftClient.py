import os
import requests
from typing import Optional, Dict, Any, List
from dotenv import load_dotenv
import json
load_dotenv()

class MintsoftAsnClient:
    BASE_URL = "https://api.mintsoft.co.uk"

    def __init__(self):
        self.username = os.getenv("MINTSOFT_USERNAME")
        self.password = os.getenv("MINTSOFT_PASSWORD")

        if not all([self.username, self.password]):
            raise RuntimeError(
                "Missing Mintsoft credentials "
                "(MINTSOFT_USERNAME / MINTSOFT_PASSWORD)"
            )

        self.api_key = self._authenticate()

    def _authenticate(self) -> str:
        url = f"{self.BASE_URL}/api/Auth"

        payload = {
            "Username": self.username,
            "Password": self.password,
        }

        r = requests.post(url, json=payload, timeout=120)
        r.raise_for_status()
        print(r.json())
        return r.json()

    def headers(self) -> Dict[str, str]:
        return {
            "ms-apikey": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
    
    def transfer_stock(self, data: Dict):
        url = f"{self.BASE_URL}/api/Warehouse/TransferStock"          

        r = requests.put(
            url,
            json=data,
            headers=self.headers(),
            timeout=120,
        )

        return r.json()
    
    def get_product_id(self, sku:str):
        url = f"{self.BASE_URL}//api/Product/Search?Search={sku}"

        r = requests.get(
            url,
            headers=self.headers(),
            timeout=120,
        )

        r.raise_for_status()
        data = r.json()
        product_id = data[0]["ID"] if data else None
        print(f"Product ID for SKU {sku}: {product_id}")
        return product_id
    
    def check_carton (self, carton_code):
        url = f'{self.BASE_URL}/api/StorageMedia/ValidateCarton?cartonCode={carton_code}'

        response = requests.get(url, headers=self.headers())

        json = response.json()

        message = json.get("Message")

        if message.startswith("Could not find a Carton with the code"):
            
            return False
        
        else:

            return True

    def create_carton(self, carton_data):
        url = f'{self.BASE_URL}/api/StorageMedia/CreateCarton?autoGenerateSSCC=false&clientId=4'

        r = requests.post(url, json = carton_data, headers=self.headers())

        if r.status_code == 200:
            print("Caja creada con exito")

        else:
            print(r.json())

        return None
    
    def get_asns(self):
        url = f"{self.BASE_URL}/api/ASN/List?ClientId=4"

        response = requests.get(url, headers=self.headers())
        response.raise_for_status()

        return(response.json())
    
    def get_asn_details(self, id):
        url = f"{self.BASE_URL}/api/ASN/{id}"

        response = requests.get(url, headers = self.headers())

        return response.json()
    
    def create_asn(self, data):
        url = f"{self.BASE_URL}/api/ASN"

        response = requests.put(url, json=data, headers=self.headers())
        
        if response.status_code == 200:
            print("Caja creada con exito")
        
        else:
            print(response.json())

        return None