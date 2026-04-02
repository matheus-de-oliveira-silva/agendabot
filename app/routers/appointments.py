from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from ..database import get_db
from ..models import Tenant, Customer, Conversation, Appointment, Service
from ..services.ai_service import chat_with_ai
from ..services.scheduler import get_available_slots, format_slots_for_ai
import json

router = APIRouter()

# Modelo da requisição de teste
class TestMessageRequest(BaseModel):
    tenant_id: str
    customer_phone: str
    message: str

class TestMessageResponse(BaseModel):
    customer_message: str
    bot_response: str
    action_taken: str
    conversation_length: int

@router.post("/test/chat", response_model=TestMessageResponse)
def test_chat(req: TestMessageRequest, db: Session = Depends(get_db)):
    """
    Rota de teste — simula uma conversa com o bot sem WhatsApp.
    Use essa rota para testar o fluxo completo localmente.
    """

    # Verifica se o tenant existe
    tenant = db.query(Tenant).filter(Tenant.id == req.tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant não encontrado")

    # Busca ou cria o cliente
    customer = db.query(Customer).filter(
        Customer.tenant_id == req.tenant_id,
        Customer.phone == req.customer_phone
    ).first()

    if not customer:
        customer = Customer(
            tenant_id=req.tenant_id,
            phone=req.customer_phone,
            wa_id=req.customer_phone
        )
        db.add(customer)
        db.commit()
        db.refresh(customer)

    # Busca ou cria a conversa
    conversation = db.query(Conversation).filter(
        Conversation.tenant_id == req.tenant_id,
        Conversation.customer_phone == req.customer_phone
    ).first()

    if not conversation:
        conversation = Conversation(
            tenant_id=req.tenant_id,
            customer_phone=req.customer_phone,
            messages="[]"
        )
        db.add(conversation)
        db.commit()
        db.refresh(conversation)

    # Carrega histórico
    history = json.loads(conversation.messages)

    # Chama a IA
    ai_response = chat_with_ai(history, req.message)

    # Processa a ação
    action_taken = ai_response.get("action", "reply")
    reply_text = ""

    if action_taken == "check_availability":
        slots = get_available_slots(
            db, req.tenant_id,
            ai_response.get("date", ""),
            ai_response.get("service", "")
        )
        reply_text = format_slots_for_ai(slots)

    elif action_taken == "create_appointment":
        # Pega o primeiro serviço disponível para o teste
        service = db.query(Service).filter(
            Service.tenant_id == req.tenant_id,
            Service.active == True
        ).first()

        if service:
            reply_text = (
                f"Agendamento confirmado! ✅\n"
                f"Pet: {ai_response.get('pet_name', 'seu pet')}\n"
                f"Serviço: {service.name}\n"
                f"Data: {ai_response.get('datetime', '')}\n"
                f"Até lá! 🐾"
            )
        else:
            reply_text = "Agendamento confirmado! Até lá! 🐾"

    else:
        reply_text = ai_response.get("message", "Desculpe, não entendi.")

    # Atualiza histórico
    history.append({"role": "user", "content": req.message})
    history.append({"role": "assistant", "content": reply_text})
    conversation.messages = json.dumps(history[-20:])
    db.commit()

    return TestMessageResponse(
        customer_message=req.message,
        bot_response=reply_text,
        action_taken=action_taken,
        conversation_length=len(history)
    )


@router.get("/test/appointments/{tenant_id}")
def list_appointments(tenant_id: str, db: Session = Depends(get_db)):
    """Lista todos os agendamentos de um tenant."""
    appointments = db.query(Appointment).filter(
        Appointment.tenant_id == tenant_id
    ).all()

    return [
        {
            "id": a.id,
            "customer_id": a.customer_id,
            "service_id": a.service_id,
            "scheduled_at": a.scheduled_at,
            "status": a.status,
            "notes": a.notes
        }
        for a in appointments
    ]


@router.get("/test/conversations/{tenant_id}")
def list_conversations(tenant_id: str, db: Session = Depends(get_db)):
    """Lista todas as conversas de um tenant."""
    conversations = db.query(Conversation).filter(
        Conversation.tenant_id == tenant_id
    ).all()

    return [
        {
            "id": c.id,
            "customer_phone": c.customer_phone,
            "messages": json.loads(c.messages),
            "state": c.state
        }
        for c in conversations
    ]
class StatusUpdate(BaseModel):
    status: str


class ManualAppointment(BaseModel):
    customer_name: str
    pet_name: str
    datetime: str


@router.put("/appointment/{appointment_id}/status")
def update_status(appointment_id: str, data: StatusUpdate, db: Session = Depends(get_db)):

    appointment = db.query(Appointment).filter(Appointment.id == appointment_id).first()

    if not appointment:
        raise HTTPException(status_code=404, detail="Agendamento não encontrado")

    appointment.status = data.status
    db.commit()

    return {"message": "status atualizado"}


@router.delete("/appointment/{appointment_id}")
def delete_appointment(appointment_id: str, db: Session = Depends(get_db)):

    appointment = db.query(Appointment).filter(Appointment.id == appointment_id).first()

    if not appointment:
        raise HTTPException(status_code=404, detail="Agendamento não encontrado")

    db.delete(appointment)
    db.commit()

    return {"message": "agendamento cancelado"}


@router.post("/manual-appointment")
def manual_appointment(data: ManualAppointment, db: Session = Depends(get_db)):

    appointment = Appointment(
        tenant_id="manual",
        customer_id="manual",
        service_id="manual",
        pet_name=data.pet_name,
        scheduled_at=data.datetime,
        status="confirmed"
    )

    db.add(appointment)
    db.commit()

    return {"message": "agendamento criado"}