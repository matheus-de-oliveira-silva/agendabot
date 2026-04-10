from openai import OpenAI
from dotenv import load_dotenv
from datetime import datetime, timedelta
import pytz
import os
import json
import re

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
BRASILIA = pytz.timezone("America/Sao_Paulo")


def agora_brasilia() -> datetime:
    return datetime.now(BRASILIA).replace(tzinfo=None)


def build_services_prompt(services: list) -> str:
    if not services:
        return "Nenhum serviço cadastrado no momento."
    lines = []
    for s in services:
        price = f"R$ {s['price']/100:.2f}" if s.get('price') else "Grátis"
        desc = f" — {s['description']}" if s.get('description') else ""
        lines.append(f'- "{s["key"]}" -> {s["name"]}: {price}, {s["duration_min"]}min{desc}')
    return "\n".join(lines)


def build_hours_prompt(tenant_config: dict) -> str:
    days_map = {
        "0": "segunda-feira", "1": "terça-feira", "2": "quarta-feira",
        "3": "quinta-feira", "4": "sexta-feira", "5": "sábado", "6": "domingo"
    }
    days_short = {
        "0": "Seg", "1": "Ter", "2": "Qua",
        "3": "Qui", "4": "Sex", "5": "Sáb", "6": "Dom"
    }
    open_days = [d.strip() for d in (tenant_config.get("open_days") or "0,1,2,3,4,5").split(",")]
    closed_days = [days_map[d] for d in ["0","1","2","3","4","5","6"] if d not in open_days]
    open_time = tenant_config.get("open_time") or "09:00"
    close_time = tenant_config.get("close_time") or "18:00"
    open_names = [days_short[d] for d in open_days if d in days_short]
    text = f"{', '.join(open_names)} das {open_time} as {close_time}."
    if closed_days:
        text += f" Fechado: {', '.join(closed_days)}."
    return text


BUSINESS_CONFIG = {
    "petshop": {
        "personality": "calorosa, simpatica e descontraida — como uma amiga que trabalha no pet shop e ama animais",
        "needs_subject_info": True,
        "subject_fields": ["nome", "raca", "peso"],
        "needs_pickup": True,
        "subject_emoji": "🐾",
        "appointment_fields": "nome do cliente, nome do {subject}, raca, peso, servico, data, hora e horario de busca",
        "fluxo_extra": "- Apos confirmar horario: colete nome do {subject}, raca e peso\n- Pergunte o horario de busca\n",
        "resumo_subject": True,
        "resumo_pickup": True,
    },
    "clinica": {
        "personality": "profissional, empatica e acolhedora — como uma recepcionista de clinica veterinaria experiente",
        "needs_subject_info": True,
        "subject_fields": ["nome", "especie/raca", "peso"],
        "needs_pickup": False,
        "subject_emoji": "🏥",
        "appointment_fields": "nome do tutor, nome do {subject}, especie/raca, peso, servico, data e hora",
        "fluxo_extra": "- Apos confirmar horario: colete nome do {subject}, especie/raca e peso\n- NAO pergunte horario de busca\n",
        "resumo_subject": True,
        "resumo_pickup": False,
    },
    "adocao": {
        "personality": "calorosa, amorosa e entusiasmada — como uma voluntaria apaixonada por animais",
        "needs_subject_info": True,
        "subject_fields": ["nome", "especie/raca"],
        "needs_pickup": False,
        "subject_emoji": "❤️",
        "appointment_fields": "nome do cliente, nome do {subject}, especie/raca, servico, data e hora",
        "fluxo_extra": "- Apos confirmar horario: colete nome do {subject} e especie/raca\n- NAO pergunte horario de busca nem peso\n",
        "resumo_subject": True,
        "resumo_pickup": False,
    },
    "barbearia": {
        "personality": "descontraida, animada e parceira — como um barbeiro amigo que conhece todo mundo pelo nome",
        "needs_subject_info": False,
        "subject_fields": [],
        "needs_pickup": False,
        "subject_emoji": "💈",
        "appointment_fields": "nome do cliente, servico, data e hora",
        "fluxo_extra": "- NAO pergunte sobre pet, raca, peso ou horario de busca\n- O cliente e o proprio sujeito do servico\n- Apos nome + servico + data/hora: vai direto pro resumo\n",
        "resumo_subject": False,
        "resumo_pickup": False,
    },
    "salao": {
        "personality": "animada, fashion e acolhedora — como uma cabeleireira amiga sempre atualizada nas tendencias",
        "needs_subject_info": False,
        "subject_fields": [],
        "needs_pickup": False,
        "subject_emoji": "💅",
        "appointment_fields": "nome do cliente, servico, data e hora",
        "fluxo_extra": "- NAO pergunte sobre pet, raca, peso ou horario de busca\n- O agendamento e para a propria cliente\n- Apos nome + servico + data/hora: vai direto pro resumo\n",
        "resumo_subject": False,
        "resumo_pickup": False,
    },
    "estetica": {
        "personality": "elegante, tranquila e atenciosa — como uma especialista em bem-estar que valoriza cada cliente",
        "needs_subject_info": False,
        "subject_fields": [],
        "needs_pickup": False,
        "subject_emoji": "🌸",
        "appointment_fields": "nome do cliente, servico, data e hora",
        "fluxo_extra": "- NAO pergunte sobre pet, raca, peso ou horario de busca\n- O agendamento e para a propria cliente\n- Apos nome + servico + data/hora: vai direto pro resumo\n",
        "resumo_subject": False,
        "resumo_pickup": False,
    },
    "outro": {
        "personality": "simpatica, profissional e prestativa — como uma boa recepcionista que conhece bem o negocio",
        "needs_subject_info": False,
        "subject_fields": [],
        "needs_pickup": False,
        "subject_emoji": "📅",
        "appointment_fields": "nome do cliente, servico, data e hora",
        "fluxo_extra": "- NAO pergunte sobre pet, raca, peso ou horario de busca, a nao ser que o servico exija\n- Apos nome + servico + data/hora: vai direto pro resumo\n",
        "resumo_subject": False,
        "resumo_pickup": False,
    },
}


def get_business_config(business_type: str) -> dict:
    return BUSINESS_CONFIG.get(business_type, BUSINESS_CONFIG["outro"])


def build_resumo_template(biz_cfg: dict, subject: str) -> str:
    emoji = biz_cfg["subject_emoji"]
    lines = []
    if biz_cfg["resumo_subject"]:
        lines.append(f'{emoji} {subject}: [nome] ([detalhe])')
    lines.append('👤 Cliente: [nome do cliente]')
    lines.append('✂️ Servico: [servico] — [preco]')
    lines.append('📅 [data] as [hora]')
    if biz_cfg["resumo_pickup"]:
        lines.append('🏠 Busca: [horario de busca]')
    return "\n".join(lines) + '\n\nTa certinho assim? 😊'


def chat_with_ai(
    conversation_history: list,
    new_message: str,
    customer_context: dict = None,
    tenant_config: dict = None,
    services: list = None
) -> dict:
    agora = agora_brasilia()
    data_atual = agora.strftime("%Y-%m-%d")
    hora_atual = agora.strftime("%H:%M")
    amanha = (agora + timedelta(days=1)).strftime("%Y-%m-%d")
    dia_semana = ["segunda-feira", "terca-feira", "quarta-feira",
                  "quinta-feira", "sexta-feira", "sabado", "domingo"][agora.weekday()]

    cfg = tenant_config or {}
    attendant_name = cfg.get("bot_attendant_name") or "Mari"
    business_name = cfg.get("bot_business_name") or cfg.get("display_name") or cfg.get("name") or "nosso estabelecimento"
    business_type = cfg.get("business_type") or "outro"
    subject = cfg.get("subject_label") or "Cliente"
    subject_plural = cfg.get("subject_label_plural") or "Clientes"

    biz_cfg = get_business_config(business_type)
    personality = biz_cfg["personality"]
    appointment_fields = biz_cfg["appointment_fields"].replace("{subject}", subject.lower())
    fluxo_extra = biz_cfg["fluxo_extra"].replace("{subject}", subject.lower())

    hours_text = build_hours_prompt(cfg)
    services_text = build_services_prompt(services or [])

    service_keys = ""
    if services:
        for s in services:
            service_keys += f'- "{s["name"]}", variacoes -> use a chave "{s["key"]}"\n'

    cliente_info = ""
    nome_cliente_conhecido = False
    if customer_context:
        nome = customer_context.get("name", "")
        pets = customer_context.get("pets", [])
        agendamentos_anteriores = customer_context.get("total_appointments", 0)
        if nome:
            nome_cliente_conhecido = True
            cliente_info += f"\nNOME DO CLIENTE: {nome}"
        if pets and biz_cfg["needs_subject_info"]:
            cliente_info += f"\n{subject_plural.upper()} CONHECIDOS:"
            for pet in pets:
                pet_str = f"\n  - {pet['name']}"
                if pet.get("breed"):
                    pet_str += f" ({pet['breed']}"
                    if pet.get("weight"):
                        pet_str += f", {pet['weight']}kg"
                    pet_str += ")"
                cliente_info += pet_str
        if agendamentos_anteriores > 0:
            cliente_info += f"\nCLIENTE RECORRENTE: sim ({agendamentos_anteriores} agendamentos anteriores)"
        else:
            cliente_info += f"\nCLIENTE RECORRENTE: nao (primeira vez)"

    nome_status = "JA CONHECIDO" if nome_cliente_conhecido else "DESCONHECIDO — pergunte na primeira resposta"
    example_service_key = services[0]["key"] if services else "servico"
    resumo_template = build_resumo_template(biz_cfg, subject)

    # Regra de campos obrigatorios
    if biz_cfg["needs_subject_info"]:
        regra_campos = f"5. So chame create_appointment com TODOS os dados: {appointment_fields}."
    else:
        regra_campos = "5. So chame create_appointment com: nome do cliente, servico, data e hora. Envie pet_name=null, pet_breed=null, pet_weight=null, pickup_time=null."

    pickup_regra = "" if biz_cfg["needs_pickup"] else "9. NAO pergunte horario de busca — este tipo de negocio nao usa esse campo.\n"

    # Exemplo de create_appointment adaptado
    if biz_cfg["needs_subject_info"] and biz_cfg["needs_pickup"]:
        create_example = f'{{"action": "create_appointment", "customer_name": "Joao", "pet_name": "Rex", "pet_breed": "Golden Retriever", "pet_weight": 30.0, "service": "{example_service_key}", "datetime": "YYYY-MM-DDTHH:MM:00", "pickup_time": "HH:MM"}}'
    elif biz_cfg["needs_subject_info"]:
        create_example = f'{{"action": "create_appointment", "customer_name": "Joao", "pet_name": "Rex", "pet_breed": "Golden Retriever", "pet_weight": 30.0, "service": "{example_service_key}", "datetime": "YYYY-MM-DDTHH:MM:00", "pickup_time": null}}'
    else:
        create_example = f'{{"action": "create_appointment", "customer_name": "Joao", "pet_name": null, "pet_breed": null, "pet_weight": null, "service": "{example_service_key}", "datetime": "YYYY-MM-DDTHH:MM:00", "pickup_time": null}}'

    system_prompt = f"""Voce e {attendant_name}, atendente virtual de {business_name}. Sua personalidade e {personality}. Converse de forma natural no WhatsApp, sem parecer robotica.

HOJE: {data_atual} ({dia_semana}) — HORA: {hora_atual} (Brasilia)
AMANHA: {amanha}
{cliente_info}

STATUS DO NOME DO CLIENTE: {nome_status}

REGRAS ABSOLUTAS (nunca viole):
1. NOME DO CLIENTE: Se DESCONHECIDO, peca o nome PRIMEIRO. Se o cliente ja mandou servico + data + horario tudo junto, peca o nome E ja chame check_availability.
2. HORARIO ESPECIFICO: Se o cliente pediu um horario especifico (ex: "as 10h"), chame check_availability e se disponivel, va DIRETO ao proximo passo.
3. NUNCA invente horarios ou precos — use sempre check_availability e os servicos listados abaixo.
4. Se o cliente ja informou dados na mensagem, NAO pergunte de novo.
{regra_campos}
6. Confirme o resumo completo ANTES de criar o agendamento e peca confirmacao explicita.
7. Fale SOMENTE sobre servicos deste estabelecimento.
8. NOME NO RESUMO: Em customer_name use o nome real coletado. NUNCA deixe vazio.
{pickup_regra}
PERSONALIDADE E TOM:
- Seja quente e proxima, como uma atendente humana real
- Use o nome do cliente quando souber
- Use emojis com naturalidade, sem exagero (2-3 por mensagem)
- Para clientes recorrentes: demonstre que reconhece
- Quando buscar horarios: "Um segundinho, vou verificar a agenda!"
- Use contracoes naturais: "ta", "pra", "vc"

FERIADOS NACIONAIS 2026:
01/01 Ano Novo | 16-17/02 Carnaval | 03/04 Sexta Santa | 21/04 Tiradentes
01/05 Dia do Trabalho | 04/06 Corpus Christi | 07/09 Independencia
12/10 N.Sra.Aparecida | 02/11 Finados | 15/11 Republica | 25/12 Natal

HORARIO DE FUNCIONAMENTO:
{hours_text}

SERVICOS DISPONIVEIS (use EXATAMENTE as chaves indicadas):
{services_text}

IDENTIFICACAO DE SERVICO:
{service_keys}

FLUXO DO AGENDAMENTO:
CENARIO A — Cliente manda tudo junto:
  1. Se nome desconhecido: peca o nome E chame check_availability
  2. Com horario disponivel: confirme e siga para coleta de dados necessarios
  3. Mostre RESUMO COMPLETO e peca confirmacao
  4. Cliente confirma -> create_appointment

CENARIO B — Cliente so diz "quero agendar":
  1. Nome desconhecido -> peca o nome
  2. Pergunte servico + data
  3. Chame check_availability -> mostre horarios disponiveis
  4. Cliente escolhe horario -> colete dados necessarios
  5. Mostre RESUMO COMPLETO e peca confirmacao
  6. Cliente confirma -> create_appointment

REGRAS ESPECIFICAS DESTE TIPO DE NEGOCIO:
{fluxo_extra}

RESUMO FINAL (use este modelo):
"Perfeito! Confirma pra mim:

{resumo_template}"

ACOES — responda SEMPRE em JSON puro:

Para verificar disponibilidade:
{{"action": "check_availability", "date": "YYYY-MM-DD", "service": "{example_service_key}"}}

Para criar agendamento:
{create_example}

Para listar agendamentos:
{{"action": "list_appointments"}}

Para cancelar:
{{"action": "cancel_appointment", "appointment_index": 1}}

Para responder normalmente:
{{"action": "reply", "message": "texto da resposta aqui"}}

IMPORTANTE:
- Responda SEMPRE em JSON puro, sem markdown, sem texto fora do JSON
- "service": use APENAS as chaves listadas em SERVICOS DISPONIVEIS
- "pet_weight": numero decimal em kg (null se nao aplicavel)
- "pickup_time": string "HH:MM" (null se nao aplicavel a este negocio)
- "pet_name", "pet_breed": null se o tipo de negocio nao exige
"""

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(conversation_history[-20:])
    messages.append({"role": "user", "content": new_message})

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=messages,
        temperature=0.7,
        max_tokens=900,
    )

    ai_text = response.choices[0].message.content.strip()
    ai_text = re.sub(r'```json\s*', '', ai_text)
    ai_text = re.sub(r'```\s*', '', ai_text)
    ai_text = ai_text.strip()

    json_match = re.search(r'\{.*\}', ai_text, re.DOTALL)
    if json_match:
        try:
            result = json.loads(json_match.group())
        except json.JSONDecodeError:
            result = {"action": "reply", "message": ai_text}
    else:
        result = {"action": "reply", "message": ai_text}

    return result


def test_ai():
    print("Testando conexao com OpenAI...")

    fake_services_pet = [
        {"key": "banho_tosa", "name": "Banho e Tosa", "price": 7000, "duration_min": 90, "description": "Banho completo com tosa"},
    ]
    fake_config_pet = {
        "bot_attendant_name": "Mari",
        "bot_business_name": "PetShop Teste",
        "business_type": "petshop",
        "open_days": "0,1,2,3,4,5",
        "open_time": "09:00",
        "close_time": "18:00",
        "subject_label": "Pet",
        "subject_label_plural": "Pets",
    }
    print("\n--- TESTE PETSHOP ---")
    r = chat_with_ai([], "Oi, quero banho e tosa pro meu golden amanha as 10h", tenant_config=fake_config_pet, services=fake_services_pet)
    print(f"Bot: {r}")

    fake_services_barb = [
        {"key": "corte_barba", "name": "Corte + Barba", "price": 6500, "duration_min": 50, "description": "Combo completo"},
    ]
    fake_config_barb = {
        "bot_attendant_name": "Leo",
        "bot_business_name": "Barbearia do Joao",
        "business_type": "barbearia",
        "open_days": "1,2,3,4,5,6",
        "open_time": "09:00",
        "close_time": "19:00",
        "subject_label": "Cliente",
        "subject_label_plural": "Clientes",
    }
    print("\n--- TESTE BARBEARIA ---")
    r2 = chat_with_ai([], "Oi quero cortar o cabelo e fazer a barba amanha as 14h", tenant_config=fake_config_barb, services=fake_services_barb)
    print(f"Bot: {r2}")


if __name__ == "__main__":
    test_ai()