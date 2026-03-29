"""
Script para popular o banco com dados de teste.
Rode uma vez para criar o tenant e serviços iniciais.
"""
from app.database import SessionLocal, engine, Base
from app.models import Tenant, Service, Customer

# Garante que as tabelas existem
Base.metadata.create_all(bind=engine)

db = SessionLocal()

# Verifica se já existe para não duplicar
existing = db.query(Tenant).filter(Tenant.name == "PetShop Teste").first()

if existing:
    print(f"Tenant já existe! ID: {existing.id}")
    tenant = existing
else:
    # Cria o tenant de teste (negócio do cliente SaaS)
    tenant = Tenant(
        name="PetShop Teste",
        phone_number_id="TEST123",       # ID fictício para testes
        wa_access_token="TOKEN_TESTE",   # Token fictício para testes
        business_type="petshop"
    )
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    print(f"Tenant criado! ID: {tenant.id}")

# Cria os serviços
services = [
    {"name": "Banho simples", "duration_min": 60, "price": 4000},
    {"name": "Banho e tosa", "duration_min": 90, "price": 7000},
    {"name": "Tosa higiênica", "duration_min": 45, "price": 3500},
]

for s in services:
    exists = db.query(Service).filter(
        Service.tenant_id == tenant.id,
        Service.name == s["name"]
    ).first()
    
    if not exists:
        service = Service(
            tenant_id=tenant.id,
            name=s["name"],
            duration_min=s["duration_min"],
            price=s["price"]
        )
        db.add(service)

db.commit()
print("Serviços criados!")

# Cria um cliente de teste
customer = db.query(Customer).filter(
    Customer.phone == "5511999999999"
).first()

if not customer:
    customer = Customer(
        tenant_id=tenant.id,
        phone="5511999999999",
        name="Cliente Teste",
        wa_id="5511999999999"
    )
    db.add(customer)
    db.commit()
    db.refresh(customer)
    print(f"Cliente criado! ID: {customer.id}")

print("\n=== IDs para usar nos testes ===")
print(f"TENANT_ID:   {tenant.id}")
print(f"CUSTOMER_ID: {customer.id}")

db.close()
