"""
evolution_helper.py — Helper centralizado para envio de mensagens via Evolution API.

ARQUITETURA MULTI-SERVIDOR:
  Cada tenant pode ter sua própria Evolution API (evolution_url + evolution_key).
  Se não configurado, usa as variáveis globais do .env.
  Isso permite escalar horizontalmente: quando um servidor encher,
  você adiciona outro e aponta novos clientes para ele.

LGPD:
  - Mensagens nunca são logadas em texto plano
  - Endereços e dados sensíveis nunca aparecem em logs
  - Cada tenant é isolado — um tenant nunca vê dados de outro
"""

import os
import httpx

APP_URL_GLOBAL = os.getenv("APP_URL", "")

# Variáveis globais — usadas como fallback quando o tenant não tem Evolution própria
EVOLUTION_API_URL_GLOBAL = os.getenv("EVOLUTION_API_URL", "")
EVOLUTION_API_KEY_GLOBAL = os.getenv("EVOLUTION_API_KEY", "")
EVOLUTION_INSTANCE_GLOBAL = os.getenv("EVOLUTION_INSTANCE", "botgen")


def get_evolution_config(tenant) -> dict:
    """
    Retorna a configuração da Evolution API para um tenant específico.

    Prioridade:
      1. evolution_url e evolution_key do próprio tenant (multi-servidor)
      2. Variáveis globais EVOLUTION_API_URL e EVOLUTION_API_KEY do .env

    Uso:
      cfg = get_evolution_config(tenant)
      url = f"{cfg['url']}/message/sendText/{cfg['instance']}"
      headers = {"apikey": cfg['key']}
    """
    evo_url = getattr(tenant, 'evolution_url', None) or EVOLUTION_API_URL_GLOBAL
    evo_key = getattr(tenant, 'evolution_key', None) or EVOLUTION_API_KEY_GLOBAL
    # A instância é sempre o phone_number_id do tenant
    instance = getattr(tenant, 'phone_number_id', None) or EVOLUTION_INSTANCE_GLOBAL

    return {
        "url":      evo_url.rstrip("/") if evo_url else "",
        "key":      evo_key,
        "instance": instance,
        "ok":       bool(evo_url and evo_key),
    }


async def send_whatsapp_message(phone: str, text: str, tenant) -> bool:
    """
    Envia mensagem WhatsApp via Evolution API do tenant.
    Retorna True se enviado com sucesso, False caso contrário.

    LGPD: o conteúdo da mensagem não é logado.
    """
    cfg = get_evolution_config(tenant)

    if not cfg["ok"]:
        print(f"[WhatsApp] Evolution não configurada para tenant {str(getattr(tenant,'id','?'))[:8]}")
        return False

    url     = f"{cfg['url']}/message/sendText/{cfg['instance']}"
    headers = {"apikey": cfg["key"], "Content-Type": "application/json"}

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                url,
                json={"number": phone, "text": text},
                headers=headers,
                timeout=10,
            )
            success = resp.status_code in (200, 201)
            if not success:
                print(f"[WhatsApp] Erro {resp.status_code} para tenant {str(getattr(tenant,'id','?'))[:8]}")
            return success
        except Exception as e:
            print(f"[WhatsApp] Exceção para tenant {str(getattr(tenant,'id','?'))[:8]}: {e}")
            return False



async def configure_instance_webhook(instance_name: str) -> bool:
    """
    Configura o webhook da instância para receber mensagens do WhatsApp.
    Chamado automaticamente após criar a instância.
    """
    if not EVOLUTION_API_URL_GLOBAL or not EVOLUTION_API_KEY_GLOBAL:
        return False

    app_url = APP_URL_GLOBAL.rstrip("/") if APP_URL_GLOBAL else ""
    if not app_url:
        print(f"[Evolution] ⚠️ APP_URL não configurada — webhook não configurado")
        return False

    webhook_url = f"{app_url}/whatsapp/webhook"
    url     = f"{EVOLUTION_API_URL_GLOBAL.rstrip('/')}/webhook/set/{instance_name}"
    headers = {"apikey": EVOLUTION_API_KEY_GLOBAL, "Content-Type": "application/json"}

    # Formato correto Evolution API v2 (flat, não aninhado)
    payload = {
        "url":              webhook_url,
        "webhook_by_events": False,
        "webhook_base64":    False,
        "events":            ["MESSAGES_UPSERT", "CONNECTION_UPDATE"],
    }

    async with httpx.AsyncClient(timeout=15) as client:
        try:
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code in (200, 201):
                print(f"[Evolution] ✅ Webhook configurado: {instance_name} → {webhook_url}")
                return True
            else:
                print(f"[Evolution] ⚠️ Erro ao configurar webhook {resp.status_code}: {resp.text[:80]}")
                return False
        except Exception as e:
            print(f"[Evolution] ⚠️ Exceção webhook: {e}")
            return False


async def create_instance(instance_name: str) -> dict:
    """
    Cria nova instância na Evolution API global e configura webhook automaticamente.
    Se já existe, garante que o webhook está configurado.
    Idempotente — não cria duplicata.
    """
    if not EVOLUTION_API_URL_GLOBAL or not EVOLUTION_API_KEY_GLOBAL:
        return {"success": False, "error": "Evolution API não configurada"}

    url     = f"{EVOLUTION_API_URL_GLOBAL.rstrip('/')}/instance/create"
    headers = {"apikey": EVOLUTION_API_KEY_GLOBAL, "Content-Type": "application/json"}

    async with httpx.AsyncClient(timeout=15) as client:
        try:
            resp = await client.post(
                url,
                json={"instanceName": instance_name, "qrcode": True, "integration": "WHATSAPP-BAILEYS"},
                headers=headers,
            )
            already_exists = resp.status_code == 409
            if resp.status_code in (200, 201) or already_exists:
                if already_exists:
                    print(f"[Evolution] Instância já existe: {instance_name}")
                else:
                    print(f"[Evolution] ✅ Instância criada: {instance_name}")
                # Configura webhook automaticamente (nova ou existente)
                await configure_instance_webhook(instance_name)
                return {"success": True, "instance": instance_name, "already_exists": already_exists}
            else:
                print(f"[Evolution] ❌ Erro ao criar {resp.status_code}: {resp.text[:80]}")
                return {"success": False, "error": f"Erro {resp.status_code}"}
        except Exception as e:
            print(f"[Evolution] ❌ Exceção criar instância: {e}")
            return {"success": False, "error": str(e)}


async def get_qrcode(instance_name: str) -> dict:
    """
    Busca QR Code da instância para exibir no setup.
    Retorna {"success": True, "qrcode": "base64..."} ou {"success": False, "error": msg}
    """
    if not EVOLUTION_API_URL_GLOBAL or not EVOLUTION_API_KEY_GLOBAL:
        return {"success": False, "error": "Evolution API não configurada"}

    url     = f"{EVOLUTION_API_URL_GLOBAL.rstrip('/')}/instance/connect/{instance_name}"
    headers = {"apikey": EVOLUTION_API_KEY_GLOBAL}

    async with httpx.AsyncClient(timeout=15) as client:
        try:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                data   = resp.json()
                qrcode = (data.get("base64") or
                          data.get("qrcode", {}).get("base64") or
                          data.get("code") or "")
                if qrcode:
                    return {"success": True, "qrcode": qrcode}
                return {"success": False, "error": "QR Code não disponível ainda"}
            return {"success": False, "error": f"Erro {resp.status_code}"}
        except Exception as e:
            return {"success": False, "error": str(e)}


async def check_connection_state(instance_name: str) -> str:
    """
    Verifica estado da conexão de uma instância.
    Retorna: "connected" | "disconnected" | "not_found" | "error"
    """
    if not EVOLUTION_API_URL_GLOBAL or not EVOLUTION_API_KEY_GLOBAL:
        return "error"

    url     = f"{EVOLUTION_API_URL_GLOBAL.rstrip('/')}/instance/connectionState/{instance_name}"
    headers = {"apikey": EVOLUTION_API_KEY_GLOBAL}

    async with httpx.AsyncClient(timeout=8) as client:
        try:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 404:
                return "not_found"
            data  = resp.json()
            state = data.get("instance", {}).get("state", "") or data.get("state", "")
            return "connected" if state in ("open", "connected") else "disconnected"
        except Exception:
            return "error"

async def send_whatsapp_via_instance(phone: str, text: str, instance: str) -> bool:
    """
    Envia mensagem usando a instância global (ex: instância do Matheus para boas-vindas).
    Usado pelo billing para enviar link de setup ao novo cliente.
    """
    if not EVOLUTION_API_URL_GLOBAL or not EVOLUTION_API_KEY_GLOBAL:
        print("[WhatsApp] Evolution global não configurada")
        return False

    phone_clean = "".join(c for c in phone if c.isdigit())
    if not phone_clean:
        return False

    url     = f"{EVOLUTION_API_URL_GLOBAL.rstrip('/')}/message/sendText/{instance}"
    headers = {"apikey": EVOLUTION_API_KEY_GLOBAL, "Content-Type": "application/json"}

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                url,
                json={"number": phone_clean, "text": text},
                headers=headers,
                timeout=10,
            )
            return resp.status_code in (200, 201)
        except Exception as e:
            print(f"[WhatsApp] Exceção envio global: {e}")
            return False