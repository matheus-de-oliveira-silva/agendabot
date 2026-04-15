"""
notifier.py — Notifica o dono do negócio quando o bot faz um agendamento.

Envia via WhatsApp (Evolution API) para o owner_phone configurado no tenant.

LGPD:
  - Endereço de entrega/busca é exibido APENAS na notificação do dono
    (ele precisa saber para ir buscar o pet)
  - O endereço NUNCA é logado em console
  - Dados do cliente só chegam ao dono do negócio, nunca a terceiros
"""

from .evolution_helper import send_whatsapp_message
from ..models import Tenant, Appointment, Service, Customer


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

    subject      = getattr(tenant, 'subject_label', 'Pet') or 'Pet'
    svc_nome     = service.name if service else "Serviço"
    cliente_nome = customer.name or customer.phone or "Cliente"
    horario      = appointment.scheduled_at.strftime("%d/%m/%Y às %H:%M")
    price_str    = f"R$ {service.price/100:.2f}" if service and service.price else ""

    # Linha do pet (quando aplicável)
    pet_linha = ""
    if appointment.pet_name:
        pet_linha = f"🐾 {subject}: {appointment.pet_name}"
        if appointment.pet_breed:
            pet_linha += f" ({appointment.pet_breed})"
        pet_linha += "\n"

    # Linha de busca (horário)
    pickup_linha = f"🏠 Busca: {appointment.pickup_time}\n" if appointment.pickup_time else ""

    # Linha de endereço — visível APENAS para o dono (LGPD)
    # O dono precisa do endereço para fazer a busca/entrega
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

    success = await send_whatsapp_message(owner_phone, mensagem, tenant)

    # LGPD: nunca loga endereço — só confirma que enviou e se tinha endereço
    if success:
        print(f"[Notif] ✅ Dono notificado | endereço: {'sim' if appointment.pickup_address else 'não'}")
    else:
        print(f"[Notif] ❌ Falha ao notificar dono")