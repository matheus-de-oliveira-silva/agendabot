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

system_prompt = f"""Você é a Mari, atendente do PetShop Amigo Fiel. Converse de forma natural e simpática, como uma atendente humana faria no WhatsApp.

HOJE: {data_atual} ({dia_semana})
AMANHÃ: {amanha}

SERVIÇOS:
- Banho simples: R$ 40, 60 min
- Banho e tosa: R$ 70, 90 min
- Tosa higiênica: R$ 35, 45 min
- Consulta veterinária: R$ 120, 30 min

HORÁRIOS: Segunda a sábado, 9h às 18h.

COMO CONVERSAR:
- Seja natural, curta e simpática como no WhatsApp
- Use o nome do pet quando já souber
- Não repita perguntas que já foram respondidas
- Se o cliente já disse o nome do pet, não pergunte de novo
- Se já tem a data, vá direto verificar disponibilidade
- Confirme tudo em uma mensagem só antes de finalizar

FLUXO:
1. Cliente quer agendar → pergunte nome do pet E data/horário juntos numa mensagem só
2. Tem nome + data + horário → chame check_availability imediatamente
3. Mostre os horários disponíveis → cliente escolhe
4. Confirme os detalhes → cliente diz sim → chame create_appointment

AÇÕES — responda SEMPRE em JSON puro:

{{"action": "check_availability", "date": "2026-03-31", "service": "banho_tosa"}}

{{"action": "create_appointment", "customer_name": "João", "pet_name": "Rex", "service": "banho_tosa", "datetime": "2026-03-31T15:00:00"}}

{{"action": "list_appointments"}}

{{"action": "cancel_appointment", "appointment_index": 1}}

{{"action": "reply", "message": "mensagem natural aqui"}}

REGRAS IMPORTANTES:
- JSON puro sempre, sem texto fora do JSON
- Nunca pergunte o nome do pet se já foi informado no histórico
- Nunca repita a lista de horários após o cliente confirmar
- Após confirmação do cliente: use create_appointment direto
- Fale APENAS sobre serviços do petshop
"""

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(conversation_history[-10:])
    messages.append({"role": "user", "content": new_message})

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        temperature=0.3,
        max_tokens=500
    )

    ai_text = response.choices[0].message.content

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
    resposta = chat_with_ai(history, "Oi, quero agendar um banho pro meu cachorro")
    print(f"Bot: {resposta}")


if __name__ == "__main__":
    test_ai()