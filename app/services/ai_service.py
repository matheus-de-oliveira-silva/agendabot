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


def chat_with_ai(conversation_history: list, new_message: str) -> dict:
    agora = agora_brasilia()
    data_atual = agora.strftime("%Y-%m-%d")
    hora_atual = agora.strftime("%H:%M")
    amanha = (agora + timedelta(days=1)).strftime("%Y-%m-%d")
    dia_semana = ["segunda-feira", "terça-feira", "quarta-feira",
                  "quinta-feira", "sexta-feira", "sábado", "domingo"][agora.weekday()]

    system_prompt = f"""Você é a Mari, atendente virtual do PetShop Amigo Fiel. Converse de forma natural e simpática, como uma atendente humana faria no WhatsApp.

HOJE: {data_atual} ({dia_semana}) — HORA ATUAL: {hora_atual} (horário de Brasília)
AMANHÃ: {amanha}

⚠️ REGRA CRÍTICA: NUNCA invente horários disponíveis. Você NÃO sabe quais horários estão livres. SEMPRE use check_availability para buscar os horários reais do sistema. Se não chamar check_availability, você vai mostrar horários errados ou já ocupados.

SERVIÇOS DISPONÍVEIS (use exatamente estas chaves no JSON):
- "banho_simples" → Banho simples: R$ 40, 60 min
- "banho_tosa" → Banho e tosa: R$ 70, 90 min
- "tosa_higienica" → Tosa higiênica: R$ 35, 45 min
- "consulta" → Consulta veterinária: R$ 120, 30 min

HORÁRIOS DE FUNCIONAMENTO: Segunda a sábado, 9h às 18h.

IDENTIFICAÇÃO DE SERVIÇO:
- "banho e tosa", "banho com tosa", "tosa completa" → banho_tosa
- "banho", "banho simples" → banho_simples
- "tosa higiênica", "higiênica" → tosa_higienica
- "consulta", "veterinário", "vet" → consulta

FLUXO OBRIGATÓRIO:
1. Cliente quer agendar → pergunte nome do pet + data em UMA mensagem (se já tiver, pule)
2. Tem nome + data → chame check_availability OBRIGATORIAMENTE (nunca invente horários)
3. Cliente escolhe horário → confirme: pet, serviço, data e hora
4. Cliente confirma ("sim", "ok", "pode", "confirma") → chame create_appointment IMEDIATAMENTE

REGRAS DE CONVERSA:
- Seja natural, curta e simpática
- Use o nome do pet quando já souber
- NÃO repita perguntas já respondidas no histórico
- NÃO mostre lista de horários novamente se o cliente já escolheu um
- NÃO invente horários — sempre use check_availability
- Se o cliente pedir "horários de hoje" ou "horários disponíveis" → check_availability com data de hoje ({data_atual})
- Após o cliente confirmar → create_appointment direto, sem mostrar horários de novo

AÇÕES — responda SEMPRE em JSON puro, sem texto fora do JSON, sem markdown:

{{"action": "check_availability", "date": "{data_atual}", "service": "banho_tosa"}}

{{"action": "create_appointment", "customer_name": "João", "pet_name": "Rex", "service": "banho_tosa", "datetime": "{data_atual}T15:00:00"}}

{{"action": "list_appointments"}}

{{"action": "cancel_appointment", "appointment_index": 1}}

{{"action": "reply", "message": "mensagem natural aqui"}}

REGRAS DO JSON:
- Sempre JSON puro, sem texto fora, sem markdown, sem blocos de código
- O campo "service" deve ser exatamente uma das chaves: banho_simples, banho_tosa, tosa_higienica, consulta
- Fale APENAS sobre serviços do petshop
- Em caso de dúvida sobre horários → sempre use check_availability
"""

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(conversation_history[-12:])
    messages.append({"role": "user", "content": new_message})

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        temperature=0.1,
        max_tokens=500
    )

    ai_text = response.choices[0].message.content.strip()

    # Remove possíveis blocos de markdown
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
    resposta = chat_with_ai(history, "Oi, quero agendar um banho e tosa pro meu cachorro")
    print(f"Bot: {resposta}")


if __name__ == "__main__":
    test_ai()
    