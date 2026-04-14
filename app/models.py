from sqlalchemy import Column, String, Integer, DateTime, Boolean, Text, Float
from sqlalchemy.sql import func
from .database import Base
import uuid

def generate_uuid():
    return str(uuid.uuid4())


class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(String, primary_key=True, default=generate_uuid)
    name = Column(String, nullable=False)
    phone_number_id = Column(String, unique=True)
    wa_access_token = Column(String)
    business_type = Column(String, default="petshop")
    created_at = Column(DateTime, server_default=func.now())

    # Auth
    dashboard_password = Column(String, nullable=True)
    dashboard_token = Column(String, nullable=True)

    # Visual
    display_name = Column(String, nullable=True)
    subject_label = Column(String, default="Pet")
    subject_label_plural = Column(String, default="Pets")
    tenant_icon = Column(String, default="🐾")          # ← NOVO: ícone personalizável

    # Bot
    bot_attendant_name = Column(String, default="Mari")
    bot_business_name = Column(String, nullable=True)
    bot_active = Column(Boolean, default=True)

    # Horários
    open_days = Column(String, default="0,1,2,3,4,5")
    open_time = Column(String, default="09:00")
    close_time = Column(String, default="18:00")

    # Notificação para o dono
    owner_phone     = Column(String, nullable=True)
    notify_new_appt = Column(Boolean, default=True)

    # Endereço (busca / entrega)
    needs_address = Column(Boolean, default=False)                        # coleta endereço do cliente?
    address_label = Column(String, default="Endereço de busca")           # label exibido no painel e no bot

    # Onboarding self-service
    setup_token = Column(String, nullable=True)   # token temporário do link /setup — anulado após uso
    setup_done  = Column(Boolean, default=False)  # True quando o cliente concluiu o wizard

    # Plano SaaS
    plan        = Column(String, default="basico")  # "basico" | "pro" | "agencia"
    plan_active = Column(Boolean, default=True)     # False = assinatura cancelada, bot pausado
    billing_email = Column(String, nullable=True)   # email do comprador na Hotmart/Kiwify


class Customer(Base):
    __tablename__ = "customers"

    id = Column(String, primary_key=True, default=generate_uuid)
    tenant_id = Column(String, nullable=False)
    phone = Column(String, nullable=False)
    name = Column(String)
    wa_id = Column(String)
    created_at = Column(DateTime, server_default=func.now())


class Pet(Base):
    __tablename__ = "pets"

    id = Column(String, primary_key=True, default=generate_uuid)
    tenant_id = Column(String, nullable=False)
    customer_id = Column(String, nullable=False)
    name = Column(String, nullable=False)
    breed = Column(String)
    weight = Column(Float)
    notes = Column(Text)
    created_at = Column(DateTime, server_default=func.now())


class Service(Base):
    __tablename__ = "services"

    id = Column(String, primary_key=True, default=generate_uuid)
    tenant_id = Column(String, nullable=False)
    name = Column(String, nullable=False)
    duration_min = Column(Integer, default=60)
    price = Column(Integer, default=0)
    active = Column(Boolean, default=True)
    description = Column(String, nullable=True)
    color = Column(String, default="#6C5CE7")


class Appointment(Base):
    __tablename__ = "appointments"

    id = Column(String, primary_key=True, default=generate_uuid)
    tenant_id = Column(String, nullable=False)
    customer_id = Column(String, nullable=False)
    service_id = Column(String, nullable=False)
    pet_id = Column(String)
    pet_name = Column(String)
    pet_breed = Column(String)
    pet_weight = Column(Float)
    scheduled_at  = Column(DateTime, nullable=False)
    pickup_time   = Column(String)
    pickup_address = Column(String, nullable=True)  # endereço de busca/entrega (quando needs_address=True)
    status = Column(String, default="confirmed")
    notes = Column(Text)
    created_at = Column(DateTime, server_default=func.now())

    # Pagamento
    payment_status = Column(String, default="pending")
    payment_method = Column(String, nullable=True)
    payment_amount = Column(Integer, nullable=True)
    payment_pix_key = Column(String, nullable=True)
    payment_paid_at = Column(DateTime, nullable=True)
    payment_notes = Column(Text, nullable=True)


class BlockedSlot(Base):
    """Horários bloqueados pelo dono — bot não agenda nesses períodos."""
    __tablename__ = "blocked_slots"

    id = Column(String, primary_key=True, default=generate_uuid)
    tenant_id = Column(String, nullable=False)
    date = Column(String, nullable=False)           # "YYYY-MM-DD"
    time = Column(String, nullable=True)            # "HH:MM" — None = dia inteiro bloqueado
    reason = Column(String, nullable=True)          # "Férias", "Folga", etc.
    created_at = Column(DateTime, server_default=func.now())


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(String, primary_key=True, default=generate_uuid)
    tenant_id = Column(String, nullable=False)
    customer_phone = Column(String, nullable=False)
    messages = Column(Text, default="[]")
    state = Column(String, default="idle")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())