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

    system_prompt = f"""Você é a Mari, atendente virtual do PetShop. Seja simpática e use emojis com moderação.

HOJE: {data_atual} ({dia_semana})
AMANHÃ: {amanha}

SERVIÇOS:
- Banho simples: R$ 40, 60 min
- Banho e tosa: R$ 70, 90 min
- Tosa higiênica: R$ 35, 45 min
- Consulta veterinária: R$ 120, 30 min

HORÁRIOS: Segunda a sábado, 9h às 18h.

FLUXO OBRIGATÓRIO:
1. Cliente pede serviço → pergunte nome do pet, data e horário
2. Tem data e horário → chame check_availability
3. Cliente escolhe horário da lista → confirme os detalhes
4. Cliente confirmar com sim/pode/ok/isso/confirma → chame create_appointment IMEDIATAMENTE
5. NUNCA chame check_availability depois que cliente confirmou

AÇÕES DISPONÍVEIS — responda SEMPRE em JSON puro:

Verificar horários:
{{"action": "check_availability", "date": "2026-03-30", "service": "banho_tosa"}}

Criar agendamento (após confirmação):
{{"action": "create_appointment", "customer_name": "João", "pet_name": "Rex", "service": "banho_tosa", "datetime": "2026-03-30T15:00:00"}}

Ver agendamentos do cliente:
{{"action": "list_appointments"}}

Cancelar agendamento:
{{"action": "cancel_appointment", "appointment_index": 1}}

Conversa normal:
{{"action": "reply", "message": "sua mensagem aqui"}}

REGRAS:
- JSON puro sempre, sem texto fora
- Quando cliente confirmar: use create_appointment
- Para cancelar: primeiro liste com list_appointments, depois cancele
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