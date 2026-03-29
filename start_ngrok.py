"""
Script que inicia o ngrok e registra o webhook no Telegram automaticamente.
Rode esse arquivo em vez de uvicorn quando quiser testar com Telegram.
"""
from pyngrok import ngrok
import httpx
import os
import subprocess
import time
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

def register_telegram_webhook(public_url: str):
    """Registra a URL pública no Telegram como webhook."""
    webhook_url = f"{public_url}/telegram/webhook"
    
    response = httpx.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/setWebhook",
        json={"url": webhook_url}
    )
    
    data = response.json()
    if data.get("ok"):
        print(f"✅ Webhook registrado com sucesso!")
        print(f"   URL: {webhook_url}")
    else:
        print(f"❌ Erro ao registrar webhook: {data}")


if __name__ == "__main__":
    print("🚀 Iniciando ngrok...")
    
    # Abre o túnel na porta 8000
    tunnel = ngrok.connect(8000)
    public_url = tunnel.public_url
    
    print(f"🌐 URL pública: {public_url}")
    
    # Registra no Telegram
    print("📱 Registrando webhook no Telegram...")
    register_telegram_webhook(public_url)
    
    print("\n✅ Tudo pronto! Agora:")
    print("   1. Deixe esse terminal aberto")
    print("   2. Em outro terminal rode: uvicorn app.main:app --reload")
    print("   3. Abra seu bot no Telegram e mande uma mensagem")
    print("\n🔴 Para parar: Ctrl+C\n")
    
    # Mantém o ngrok rodando
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nEncerrando ngrok...")
        ngrok.disconnect(public_url)
