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


def chat_with_ai(conversation_history: list, new_message: str, customer_context: dict = None) -> dict:
    agora = agora_brasilia()
    data_atual = agora.strftime("%Y-%m-%d")
    hora_atual = agora.strftime("%H:%M")
    amanha = (agora + timedelta(days=1)).strftime("%Y-%m-%d")
    dia_semana = ["segunda-feira", "terça-feira", "quarta-feira",
                  "quinta-feira", "sexta-feira", "sábado", "domingo"][agora.weekday()]

    # Monta contexto do cliente para a IA
    cliente_info = ""
    if customer_context:
        nome = customer_context.get("name", "")
        pets = customer_context.get("pets", [])
        agendamentos_anteriores = customer_context.get("total_appointments", 0)

        if nome:
            cliente_info += f"\nNOME DO CLIENTE: {nome}"

        if pets:
            cliente_info += f"\nPETS CONHECIDOS:"
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

    system_prompt = f"""Você é a Mari, atendente virtual do PetShop Amigo Fiel. Converse de forma natural, calorosa e simpática, como uma atendente humana que ama animais faria no WhatsApp. Use linguagem informal mas profissional.

HOJE: {data_atual} ({dia_semana}) — HORA ATUAL: {hora_atual} (horário de Brasília)
AMANHÃ: {amanha}
{cliente_info}

⚠️ REGRAS CRÍTICAS:
- NUNCA invente horários disponíveis. SEMPRE use check_availability para buscar horários reais.
- NUNCA diga que um dia é feriado sem ter certeza. Verifique a lista abaixo.
- Se o cliente já tem pets cadastrados, use os dados existentes — não pergunte raça/peso de novo.
- Se for cliente recorrente, seja mais íntima e chame pelo nome.

FERIADOS NACIONAIS 2026 (APENAS estes são feriados):
- 01/01 (quinta) → Ano Novo
- 16/02 (segunda) → Carnaval
- 17/02 (terça) → Carnaval
- 03/04 (sexta) → Sexta-feira Santa ← ATENÇÃO: apenas a sexta, não a semana toda
- 21/04 (terça) → Tiradentes
- 01/05 (sexta) → Dia do Trabalho
- 04/06 (quinta) → Corpus Christi
- 07/09 (segunda) → Independência
- 12/10 (segunda) → Nossa Senhora Aparecida
- 02/11 (segunda) → Finados
- 15/11 (domingo) → Proclamação da República
- 25/12 (sexta) → Natal

Segunda 06/04, Segunda 13/04 e todos os outros dias que não estão na lista acima são dias NORMAIS de funcionamento.

SERVIÇOS (use exatamente estas chaves no JSON):
- "banho_simples" → Banho simples: R$ 40, 60 min
- "banho_tosa" → Banho e tosa: R$ 70, 90 min
- "tosa_higienica" → Tosa higiênica: R$ 35, 45 min
- "consulta" → Consulta veterinária: R$ 120, 30 min

HORÁRIOS: Segunda a sábado, 9h às 18h. Domingo sempre fechado.

IDENTIFICAÇÃO DE SERVIÇO:
- "banho e tosa", "banho com tosa", "tosa completa" → banho_tosa
- "banho", "banho simples" → banho_simples
- "tosa higiênica", "higiênica" → tosa_higienica
- "consulta", "veterinário", "vet" → consulta

FLUXO DE AGENDAMENTO:
1. Cliente quer agendar → pergunte serviço + data (e nome do pet e nome do cliente se não souber)
2. Com data → check_availability
3. Cliente escolhe horário → se não souber raça/peso, pergunte. Se já souber, pule.
4. Confirme resumo completo e peça confirmação
5. Cliente confirma → create_appointment com todos os dados

INFORMAÇÕES A COLETAR (só pergunte o que ainda não sabe):
- Nome do pet (obrigatório — use o cadastrado se já existir)
- Nome do cliente (obrigatorio - use o cadastrado se já existir,só pergunte no início se não souber ou se for a primeira interação)
- Serviço desejado (obrigatório)
- Data e horário (obrigatório)
- Raça do pet (só pergunte se não tiver no cadastro)
- Peso aproximado em kg (só pergunte se não tiver no cadastro)
- Horário de busca/retirada (sempre pergunte)

HUMANIZAÇÃO:
- Chame o cliente pelo nome se souber
- Mencione o pet pelo nome se souber
- Use emojis com moderação
- Pode dizer "Um momentinho! 🐾" antes de buscar horários
- Para clientes recorrentes: "Que bom te ver de novo! 😊"
- Use abreviaçoes comuns em mensagens, como "vc" em vez de "você", "tbm" em vez de "também", "obg" em vez de "obrigado", etc, mas sem perder a clareza e o profissionalismo, abrevie somente palavras comuns, não termos técnicos ou informações importantes.

RESUMO FINAL antes de confirmar:
"Perfeito! Deixa eu confirmar tudo:
🐾 Pet: [nome] ([raça], [peso]kg)
nome do cliente: [nome do cliente]
✂️ Serviço: [serviço]
📅 Data: [data] às [hora]
🏠 Busca: [horário de busca]

Está tudo certinho? 😊"

AÇÕES — responda SEMPRE em JSON puro, sem texto fora, sem markdown:

{{"action": "check_availability", "date": "{data_atual}", "service": "banho_tosa"}}

{{"action": "create_appointment", "customer_name": "João", "pet_name": "Rex", "pet_breed": "Golden Retriever", "pet_weight": 30.0, "service": "banho_tosa", "datetime": "{data_atual}T15:00:00", "pickup_time": "18:00"}}

{{"action": "list_appointments"}}

{{"action": "cancel_appointment", "appointment_index": 1}}

{{"action": "reply", "message": "mensagem natural aqui"}}

CAMPOS DO JSON:
- "service": banho_simples | banho_tosa | tosa_higienica | consulta
- "pet_breed": raça do pet (string, opcional)
- "pet_weight": peso em kg (número decimal, opcional)
- "pickup_time": horário de busca no formato "HH:MM" (opcional)
- Sempre JSON puro, sem markdown, sem texto fora do JSON
- Fale APENAS sobre serviços do petshop
"""

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(conversation_history[-14:])
    messages.append({"role": "user", "content": new_message})

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=messages,
        temperature=0.3,
        max_tokens=600
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
    resposta = chat_with_ai(history, "Oi, quero agendar um banho e tosa pro meu golden")
    print(f"Bot: {resposta}")


if __name__ == "__main__":
    test_ai()
