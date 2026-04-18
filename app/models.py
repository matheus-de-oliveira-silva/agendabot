"""
models.py — Modelos SQLAlchemy do BotGen SaaS.

LGPD:
  - phone/email nunca logados em plaintext
  - messages (Conversation) tem reset de 24h no código + deve ser limpo periodicamente
  - pickup_address armazenado apenas para o dono do negócio acessar, nunca logado
  - Isolamento multi-tenant: todas as queries filtram por tenant_id
"""

from sqlalchemy import Column, String, Integer, DateTime, Boolean, Text, Float, Date, Index
from sqlalchemy.sql import func
from .database import Base
import uuid


def generate_uuid():
    return str(uuid.uuid4())


class Tenant(Base):
    __tablename__ = "tenants"

    id               = Column(String, primary_key=True, default=generate_uuid)
    name             = Column(String, nullable=False)
    phone_number_id  = Column(String, unique=True, nullable=True)
    wa_access_token  = Column(String, nullable=True)
    business_type    = Column(String, default="petshop")
    created_at       = Column(DateTime, server_default=func.now())

    # Auth
    dashboard_password = Column(String, nullable=True)
    dashboard_token    = Column(String, nullable=True)

    # Visual
    display_name         = Column(String, nullable=True)
    subject_label        = Column(String, default="Pet")
    subject_label_plural = Column(String, default="Pets")
    tenant_icon          = Column(String, default="🐾")

    # Bot
    bot_attendant_name = Column(String, default="Mari")
    bot_business_name  = Column(String, nullable=True)
    bot_active         = Column(Boolean, default=True)

    # Horários
    open_days  = Column(String, default="0,1,2,3,4,5")
    open_time  = Column(String, default="09:00")
    close_time = Column(String, default="18:00")

    # Notificação para o dono
    owner_phone     = Column(String, nullable=True)
    notify_new_appt = Column(Boolean, default=True)

    # Endereço (busca / entrega)
    needs_address = Column(Boolean, default=False)
    address_label = Column(String, default="Endereço de busca")

    # Onboarding self-service
    # NOTA: setup_token NÃO é zerado após conclusão — admin precisa do link
    # Para revogar: admin gera novo token via /admin/tenant/{id}/resend-setup
    setup_token = Column(String, nullable=True)
    setup_done  = Column(Boolean, default=False)

    # Plano SaaS
    plan              = Column(String, default="basico")   # "basico" | "pro" | "agencia"
    plan_active       = Column(Boolean, default=True)      # False = assinatura cancelada
    billing_email     = Column(String, nullable=True)      # email do comprador na Kiwify
    plan_tenant_group = Column(String, nullable=True)      # agência: email do comprador principal
    next_billing_date = Column(Date, nullable=True)        # para aviso de vencimento (migration v7)

    # Pagamento — chave PIX e formas aceitas
    # O bot informa automaticamente após confirmar agendamento
    pix_key           = Column(String, nullable=True)   # Ex: "11999999999" ou "email@empresa.com"
    # ── Campos configuráveis que a IA coleta ────────────────────────────────────
    # JSON: {"pet_name":true,"pet_breed":true,"pet_weight":false,...}
    # Se null → usa defaults do business_type
    collect_fields    = Column(Text, nullable=True)
    pix_type          = Column(String, default="telefone")  # "telefone"|"email"|"cpf"|"cnpj"|"aleatoria"
    payment_methods   = Column(String, nullable=True)   # Ex: "pix,dinheiro,cartao" (separado por vírgula)
    payment_note      = Column(String, nullable=True)   # Ex: "Pagamento na entrega ou via PIX"

    # Evolution API por tenant (escalabilidade multi-servidor)
    # Se vazio, usa variáveis globais EVOLUTION_API_URL e EVOLUTION_API_KEY
    # LGPD: cada tenant usa instância própria — isolamento total de mensagens
    evolution_url = Column(String, nullable=True)
    evolution_key = Column(String, nullable=True)


class Customer(Base):
    __tablename__ = "customers"

    id         = Column(String, primary_key=True, default=generate_uuid)
    tenant_id  = Column(String, nullable=False, index=True)   # índice para performance
    phone      = Column(String, nullable=False)               # LGPD: nunca logado em plaintext
    name       = Column(String, nullable=True)
    wa_id      = Column(String, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    # Índice composto: busca de cliente por tenant+phone (operação mais frequente)
    __table_args__ = (
        Index("ix_customers_tenant_phone", "tenant_id", "phone"),
    )


class Pet(Base):
    __tablename__ = "pets"

    id          = Column(String, primary_key=True, default=generate_uuid)
    tenant_id   = Column(String, nullable=False, index=True)
    customer_id = Column(String, nullable=False, index=True)
    name        = Column(String, nullable=False)
    breed       = Column(String, nullable=True)
    weight      = Column(Float, nullable=True)
    notes       = Column(Text, nullable=True)
    created_at  = Column(DateTime, server_default=func.now())


class Service(Base):
    __tablename__ = "services"

    id           = Column(String, primary_key=True, default=generate_uuid)
    tenant_id    = Column(String, nullable=False, index=True)
    name         = Column(String, nullable=False)
    duration_min = Column(Integer, default=60)
    price        = Column(Integer, default=0)    # centavos
    active       = Column(Boolean, default=True)
    description  = Column(String, nullable=True)
    color        = Column(String, default="#6C5CE7")


class Appointment(Base):
    __tablename__ = "appointments"

    id             = Column(String, primary_key=True, default=generate_uuid)
    tenant_id      = Column(String, nullable=False, index=True)
    customer_id    = Column(String, nullable=False, index=True)
    service_id     = Column(String, nullable=False)
    pet_id         = Column(String, nullable=True)
    pet_name       = Column(String, nullable=True)
    pet_breed      = Column(String, nullable=True)
    pet_weight     = Column(Float, nullable=True)
    scheduled_at   = Column(DateTime, nullable=False, index=True)
    pickup_time    = Column(String, nullable=True)
    # LGPD: endereço nunca logado em console — exibido apenas no painel do dono
    pickup_address = Column(String, nullable=True)
    status         = Column(String, default="confirmed")
    notes          = Column(Text, nullable=True)
    created_at     = Column(DateTime, server_default=func.now())

    # Pagamento
    payment_status  = Column(String, default="pending")
    payment_method  = Column(String, nullable=True)
    payment_amount  = Column(Integer, nullable=True)   # centavos
    payment_pix_key = Column(String, nullable=True)
    payment_paid_at = Column(DateTime, nullable=True)
    payment_notes   = Column(Text, nullable=True)

    # Índice composto: agendamentos por tenant e data (operação mais frequente no dashboard)
    __table_args__ = (
        Index("ix_appointments_tenant_date", "tenant_id", "scheduled_at"),
    )


class BlockedSlot(Base):
    __tablename__ = "blocked_slots"

    id         = Column(String, primary_key=True, default=generate_uuid)
    tenant_id  = Column(String, nullable=False, index=True)
    date       = Column(String, nullable=False)    # "YYYY-MM-DD"
    time       = Column(String, nullable=True)     # "HH:MM" — None = dia inteiro
    reason     = Column(String, nullable=True)
    created_at = Column(DateTime, server_default=func.now())


class Conversation(Base):
    __tablename__ = "conversations"

    id             = Column(String, primary_key=True, default=generate_uuid)
    tenant_id      = Column(String, nullable=False, index=True)
    # LGPD: phone nunca logado — só usado como chave de busca
    customer_phone = Column(String, nullable=False)
    # LGPD: messages armazena conteúdo da conversa — resetado após 24h de inatividade
    # Para conformidade LGPD, execute limpeza periódica de conversas > 30 dias
    messages       = Column(Text, default="[]")
    state          = Column(String, default="idle")
    updated_at     = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_conversations_tenant_phone", "tenant_id", "customer_phone"),
    )