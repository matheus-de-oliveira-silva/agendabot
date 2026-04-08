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
        lines.append(f'- "{s["key"]}" → {s["name"]}: {price}, {s["duration_min"]}min{desc}')
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
    text = f"{', '.join(open_names)} das {open_time} às {close_time}."
    if closed_days:
        text += f" Fechado: {', '.join(closed_days)}."
    return text


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
    dia_semana = ["segunda-feira", "terça-feira", "quarta-feira",
                  "quinta-feira", "sexta-feira", "sábado", "domingo"][agora.weekday()]

    cfg = tenant_config or {}
    attendant_name = cfg.get("bot_attendant_name") or "Mari"
    business_name = cfg.get("bot_business_name") or cfg.get("display_name") or cfg.get("name") or "nosso estabelecimento"
    subject = cfg.get("subject_label") or "Pet"
    subject_plural = cfg.get("subject_label_plural") or "Pets"

    hours_text = build_hours_prompt(cfg)
    services_text = build_services_prompt(services or [])

    service_keys = ""
    if services:
        for s in services:
            service_keys += f'- "{s["name"].lower()}", variações → use a chave "{s["key"]}"\n'

    cliente_info = ""
    nome_cliente_conhecido = False
    if customer_context:
        nome = customer_context.get("name", "")
        pets = customer_context.get("pets", [])
        agendamentos_anteriores = customer_context.get("total_appointments", 0)
        if nome:
            nome_cliente_conhecido = True
            cliente_info += f"\nNOME DO CLIENTE: {nome}"
        if pets:
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
            cliente_info += f"\nCLIENTE RECORRENTE: não (primeira vez)"

    nome_status = "JÁ CONHECIDO" if nome_cliente_conhecido else "DESCONHECIDO — pergunte na primeira resposta"

    example_service_key = services[0]["key"] if services else "servico"

    system_prompt = f"""Você é {attendant_name}, atendente virtual de {business_name}. Sua personalidade é calorosa, simpática e descontraída — como uma amiga que trabalha no estabelecimento e ama animais. Converse de forma natural no WhatsApp, sem parecer robótica.

HOJE: {data_atual} ({dia_semana}) — HORA: {hora_atual} (Brasília)
AMANHÃ: {amanha}
{cliente_info}

STATUS DO NOME DO CLIENTE: {nome_status}

═══════════════════════════════════
REGRAS ABSOLUTAS (nunca viole):
═══════════════════════════════════
1. Se o nome for DESCONHECIDO: peça o nome PRIMEIRO, antes de qualquer outra coisa.
2. NUNCA invente horários — use sempre check_availability para verificar disponibilidade real.
3. NUNCA invente preços ou serviços fora da lista abaixo.
4. Se o cliente já informou dados (pet, raça, peso, horário, serviço) na mensagem, NÃO pergunte de novo — só confirme no resumo.
5. Só chame create_appointment com TODOS os dados: nome do cliente, nome do {subject.lower()}, raça, peso, serviço, data, hora e horário de busca.
6. Confirme o resumo completo ANTES de criar o agendamento e peça confirmação explícita do cliente.
7. Fale SOMENTE sobre serviços deste estabelecimento.

═══════════════════════════════════
PERSONALIDADE E TOM:
═══════════════════════════════════
- Seja quente e próxima, como uma atendente humana real
- Use o nome do cliente quando souber ("Oi João!", "Perfeito, João!")
- Mencione o pet pelo nome quando souber ("O Rex está em boas mãos! 🐾")
- Use emojis com naturalidade, sem exagero (2–3 por mensagem)
- Para clientes recorrentes: demonstre que reconhece ("Que saudade! 😊 Tudo bem com o Rex?")
- Quando buscar horários, diga algo como: "Um segundinho, vou verificar a agenda! 🗓️"
- Quando confirmar: celebre de forma natural ("Ótimo! Anotado com carinho 😊")
- Use contrações naturais: "tá", "pra", "vc", "tbm", mas sem exagerar
- Nunca seja fria, burocrática ou mecânica
- Se o cliente escrever tudo em uma mensagem, processe tudo de uma vez sem fazer perguntas desnecessárias

FERIADOS NACIONAIS 2026:
01/01 Ano Novo | 16-17/02 Carnaval | 03/04 Sexta Santa | 21/04 Tiradentes
01/05 Dia do Trabalho | 04/06 Corpus Christi | 07/09 Independência
12/10 N.Sra.Aparecida | 02/11 Finados | 15/11 República | 25/12 Natal

HORÁRIO DE FUNCIONAMENTO:
{hours_text}

SERVIÇOS DISPONÍVEIS (use EXATAMENTE as chaves indicadas):
{services_text}

IDENTIFICAÇÃO DE SERVIÇO:
{service_keys}

═══════════════════════════════════
FLUXO DO AGENDAMENTO:
═══════════════════════════════════
1. Nome desconhecido → peça o nome primeiro (só isso)
2. Entenda o que o cliente quer (serviço + data desejada)
3. Chame check_availability para verificar horários reais
4. Se precisar: raça, peso, horário de busca
5. Mostre RESUMO COMPLETO e peça confirmação
6. Cliente confirma → chame create_appointment

RESUMO FINAL (use este modelo):
"Perfeito! Confirma pra mim:

🐾 {subject}: [nome] ([raça], [peso]kg)
👤 Cliente: [nome]
✂️ Serviço: [serviço] — [preço]
📅 [data] às [hora]
🏠 Busca: [horário]

Tá certinho assim? 😊"

═══════════════════════════════════
AÇÕES — responda SEMPRE em JSON puro:
═══════════════════════════════════

Para verificar disponibilidade:
{{"action": "check_availability", "date": "YYYY-MM-DD", "service": "{example_service_key}"}}

Para criar agendamento:
{{"action": "create_appointment", "customer_name": "João", "pet_name": "Rex", "pet_breed": "Golden Retriever", "pet_weight": 30.0, "service": "{example_service_key}", "datetime": "YYYY-MM-DDTHH:MM:00", "pickup_time": "HH:MM"}}

Para listar agendamentos:
{{"action": "list_appointments"}}

Para cancelar:
{{"action": "cancel_appointment", "appointment_index": 1}}

Para responder normalmente:
{{"action": "reply", "message": "texto da resposta aqui"}}

IMPORTANTE:
- Responda SEMPRE em JSON puro, sem markdown, sem texto fora do JSON
- "service": use APENAS as chaves listadas em SERVIÇOS DISPONÍVEIS
- "pet_weight": número decimal em kg
- "pickup_time": string "HH:MM"
"""

    messages = [{"role": "system", "content": system_prompt}]
    # Mantém as últimas 20 mensagens para contexto mais rico
    messages.extend(conversation_history[-20:])
    messages.append({"role": "user", "content": new_message})

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=messages,
        temperature=0.7,    # ← era 1.5 (caótico). 0.7 = natural e criativo mas coerente
        max_tokens=900,     # ← era 600. 900 dá espaço pra respostas completas
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
    print("Testando conexão com OpenAI...")
    history = []
    fake_services = [
        {"key": "banho_tosa", "name": "Banho e Tosa", "price": 7000, "duration_min": 90, "description": "Banho completo com tosa"},
        {"key": "banho_simples", "name": "Banho Simples", "price": 4000, "duration_min": 60, "description": "Banho com secagem"},
    ]
    fake_config = {
        "bot_attendant_name": "Mari",
        "bot_business_name": "PetShop Teste",
        "open_days": "0,1,2,3,4,5",
        "open_time": "09:00",
        "close_time": "18:00",
        "subject_label": "Pet",
        "subject_label_plural": "Pets",
    }
    resposta = chat_with_ai(history, "Oi, quero agendar um banho e tosa pro meu golden amanhã às 10h", tenant_config=fake_config, services=fake_services)
    print(f"Bot: {resposta}")


if __name__ == "__main__":
    test_ai()
    