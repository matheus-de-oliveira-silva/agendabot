"""
Script para criar o tenant no banco de PRODUÇÃO via API.
Rode esse arquivo uma vez para configurar o Railway.
"""
import httpx

BASE_URL = "https://web-production-c1b1c.up.railway.app"

# Cria uma rota temporária de setup — vamos adicionar no main.py
response = httpx.post(f"{BASE_URL}/setup/tenant", json={
    "name": "PetShop Teste",
    "business_type": "petshop",
    "phone_number_id": "TEST123",
    "wa_access_token": "TOKEN_TESTE"
}, timeout=30)

print(response.json())
