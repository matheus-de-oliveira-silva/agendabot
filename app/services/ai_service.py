from openai import OpenAI
from dotenv import load_dotenv
from datetime import datetime, timedelta
import os
import json
import re

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def chat_with_ai(conversation_history: list, new_message: str) -> dict:

    hoje = datetime.now()
    data_atual = hoje.strftime("%Y-%m-%d")
    amanha = (hoje + timedelta(days=1)).strftime("%Y-%m-%d")
    dia_semana = ["segunda-feira","terça-feira","quarta-feira",
                  "quinta-feira","sexta-feira","sábado","domingo"][hoje.weekday()]

    system_prompt = f"""Você é a Mari, atendente virtual do PetShop Amigo Fiel. Converse de forma natural e simpática, como uma atendente humana faria no WhatsApp.

HOJE: {data_atual} ({dia_semana})
AMANHÃ: {amanha}

SERVIÇOS DISPONÍVEIS (use exatamente estas chaves no JSON):
- "banho_simples" → Banho simples: R$ 40, 60 min
- "banho_tosa" → Banho e tosa: R$ 70, 90 min
- "tosa_higienica" → Tosa higiênica: R$ 35, 45 min
- "consulta" → Consulta veterinária: R$ 120, 30 min

HORÁRIOS: Segunda a sábado, 9h às 18h.

REGRAS DE CONVERSA:
- Seja natural, curta e simpática
- Use o nome do pet quando já souber
- NÃO repita perguntas já respondidas no histórico
- NÃO mostre lista de horários novamente se o cliente já escolheu um
- Se o cliente confirmar ("sim", "pode ser", "ok", "confirma"), use create_appointment DIRETO
- Sempre identifique o serviço correto: "banho e tosa" = banho_tosa, "banho" sozinho = banho_simples

FLUXO CORRETO:
1. Cliente quer agendar → pergunte nome do pet + data/horário em UMA mensagem
2. Tem nome + data → check_availability para ver horários
3. Cliente escolhe horário → confirme os detalhes (pet, serviço, data/hora)
4. Cliente diz "sim" ou confirma → create_appointment IMEDIATAMENTE (não mostre horários de novo!)

IDENTIFICAÇÃO DE SERVIÇO:
- "banho e tosa", "banho com tosa", "tosa completa" → banho_tosa
- "banho", "banho simples" → banho_simples  
- "tosa higiênica", "higiênica" → tosa_higienica
- "consulta", "veterinário", "vet" → consulta

AÇÕES — responda SEMPRE em JSON puro, sem texto fora do JSON:

{{"action": "check_availability", "date": "2026-03-31", "service": "banho_tosa"}}

{{"action": "create_appointment", "customer_name": "João", "pet_name": "Rex", "service": "banho_tosa", "datetime": "2026-03-31T15:00:00"}}

{{"action": "list_appointments"}}

{{"action": "cancel_appointment", "appointment_index": 1}}

{{"action": "reply", "message": "mensagem natural aqui"}}

IMPORTANTE:
- JSON puro sempre, sem markdown, sem texto fora do JSON
- O campo "service" deve ser exatamente uma das chaves: banho_simples, banho_tosa, tosa_higienica, consulta
- Fale APENAS sobre serviços do petshop
"""

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(conversation_history[-12:])
    messages.append({"role": "user", "content": new_message})

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        temperature=0.2,
        max_tokens=500
    )

    ai_text = response.choices[0].message.content.strip()

    # Remove possíveis blocos de markdown
    ai_text = re.sub(r'```json\s*', '', ai_text)
    ai_text = re.sub(r'```\s*', '', ai_text)

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