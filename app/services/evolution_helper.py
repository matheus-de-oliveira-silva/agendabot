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