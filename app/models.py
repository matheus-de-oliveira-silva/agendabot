from sqlalchemy import Column, String, Integer, DateTime, Boolean, Text
from sqlalchemy.sql import func
from .database import Base
import uuid

def generate_uuid():
    return str(uuid.uuid4())

# Tabela de negócios (cada cliente do SaaS)
class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(String, primary_key=True, default=generate_uuid)
    name = Column(String, nullable=False)
    phone_number_id = Column(String, unique=True)
    wa_access_token = Column(String)
    business_type = Column(String, default="petshop")
    created_at = Column(DateTime, server_default=func.now())

# Tabela de clientes finais (quem manda mensagem no WhatsApp)
class Customer(Base):
    __tablename__ = "customers"

    id = Column(String, primary_key=True, default=generate_uuid)
    tenant_id = Column(String, nullable=False)
    phone = Column(String, nullable=False)
    name = Column(String)
    wa_id = Column(String)
    created_at = Column(DateTime, server_default=func.now())

# Tabela de serviços (banho, tosa, corte etc)
class Service(Base):
    __tablename__ = "services"

    id = Column(String, primary_key=True, default=generate_uuid)
    tenant_id = Column(String, nullable=False)
    name = Column(String, nullable=False)
    duration_min = Column(Integer, default=60)
    price = Column(Integer, default=0)
    active = Column(Boolean, default=True)

# Tabela de agendamentos
class Appointment(Base):
    __tablename__ = "appointments"

    id = Column(String, primary_key=True, default=generate_uuid)
    tenant_id = Column(String, nullable=False)
    customer_id = Column(String, nullable=False)
    service_id = Column(String, nullable=False)
    scheduled_at = Column(DateTime, nullable=False)
    status = Column(String, default="pending")
    notes = Column(Text)
    created_at = Column(DateTime, server_default=func.now())

# Tabela de conversas (histórico com a IA)
class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(String, primary_key=True, default=generate_uuid)
    tenant_id = Column(String, nullable=False)
    customer_phone = Column(String, nullable=False)
    messages = Column(Text, default="[]")
    state = Column(String, default="idle")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())