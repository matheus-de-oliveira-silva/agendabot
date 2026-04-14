"""
notifier.py — Notifica o dono do negócio quando o bot faz um agendamento.
Envia via WhatsApp (Evolution API) para o owner_phone configurado no tenant.
"""
import os, httpx
from ..models import Tenant, Appointment, Service, Customer

EVOLUTION_API_URL = os.getenv("EVOLUTION_API_URL")
EVOLUTION_API_KEY = os.getenv("EVOLUTION_API_KEY")


async def notify_owner_new_appointment(
    tenant: Tenant,
    appointment: Appointment,
    customer: Customer,
    service: Service,
):
    """
    Envia notificação WhatsApp para o dono quando o bot confirmar um agendamento.
    Só envia se owner_phone estiver configurado e notify_new_appt for True.
    """
    owner_phone = getattr(tenant, 'owner_phone', None)
    notify      = getattr(tenant, 'notify_new_appt', True)

    if not owner_phone or not notify:
        return

    if not EVOLUTION_API_URL or not EVOLUTION_API_KEY:
        print(f"[Notif] Evolution não configurada — sem notificação para {owner_phone}")
        return

    subject    = getattr(tenant, 'subject_label', 'Pet') or 'Pet'
    svc_nome   = service.name if service else "Serviço"
    cliente_nome = customer.name or customer.phone or "Cliente"
    horario    = appointment.scheduled_at.strftime("%d/%m/%Y às %H:%M")
    price_str  = f"R$ {service.price/100:.2f}" if service and service.price else ""

    # Linha do pet (quando aplicável)
    pet_linha = ""
    if appointment.pet_name:
        pet_linha = f"🐾 {subject}: {appointment.pet_name}"
        if appointment.pet_breed:
            pet_linha += f" ({appointment.pet_breed})"
        pet_linha += "\n"

    # Linha de busca (horário)
    pickup_linha = f"🏠 Busca: {appointment.pickup_time}\n" if appointment.pickup_time else ""

    # ── Etapa 5: linha de endereço — visível APENAS para o dono logado ───────
    # O endereço aparece na notificação do dono pois ele precisa buscar o cliente.
    # LGPD: não aparece em logs de console (ver abaixo).
    address_linha = ""
    if getattr(appointment, 'pickup_address', None):
        address_label = getattr(tenant, 'address_label', 'Endereço') or 'Endereço'
        address_linha = f"📍 {address_label}: {appointment.pickup_address}\n"

    mensagem = (
        f"🔔 *Novo agendamento pelo bot!*\n\n"
        f"👤 Cliente: {cliente_nome}\n"
        f"{pet_linha}"
        f"✂️ Serviço: {svc_nome}{' — ' + price_str if price_str else ''}\n"
        f"📅 {horario}\n"
        f"{pickup_linha}"
        f"{address_linha}"
        f"\nAcesse o painel para ver detalhes. 📋"
    ).strip()

    instance = getattr(tenant, 'phone_number_id', None) or os.getenv("EVOLUTION_INSTANCE", "agendabot")
    url      = f"{EVOLUTION_API_URL}/message/sendText/{instance}"
    headers  = {"apikey": EVOLUTION_API_KEY, "Content-Type": "application/json"}

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                url,
                json={"number": owner_phone, "text": mensagem},
                headers=headers,
                timeout=10,
            )
            if resp.status_code in (200, 201):
                # LGPD: nunca loga o endereço — só confirma que enviou
                print(f"[Notif] ✅ Dono notificado: {owner_phone} | endereço: {'sim' if appointment.pickup_address else 'não'}")
            else:
                print(f"[Notif] ❌ Erro {resp.status_code}: {resp.text[:80]}")
        except Exception as e:
            print(f"[Notif] ❌ Exceção: {e}")