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
    business_type = Column(String, default="petshop")  # petshop | clinica | adocao | outro
    created_at = Column(DateTime, server_default=func.now())

    # Auth do dashboard
    dashboard_password = Column(String, nullable=True)  # hash bcrypt
    dashboard_token = Column(String, nullable=True)     # token de sessão

    # Configurações visuais/nome
    display_name = Column(String, nullable=True)        # nome exibido no dashboard
    subject_label = Column(String, default="Pet")       # "Pet", "Animal", "Paciente"
    subject_label_plural = Column(String, default="Pets")


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
    price = Column(Integer, default=0)         # em centavos (ex: 7000 = R$70,00)
    active = Column(Boolean, default=True)
    # Campos novos
    description = Column(String, nullable=True)  # descrição curta p/ o bot
    color = Column(String, default="#6C5CE7")     # cor no dashboard


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
    scheduled_at = Column(DateTime, nullable=False)
    pickup_time = Column(String)
    status = Column(String, default="confirmed")
    notes = Column(Text)
    created_at = Column(DateTime, server_default=func.now())


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(String, primary_key=True, default=generate_uuid)
    tenant_id = Column(String, nullable=False)
    customer_phone = Column(String, nullable=False)
    messages = Column(Text, default="[]")
    state = Column(String, default="idle")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    