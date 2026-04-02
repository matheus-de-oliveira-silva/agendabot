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


# --------------------------------------------------
# HORÁRIO ATUAL
# --------------------------------------------------

def agora_brasilia():
    return datetime.now(BRASILIA).replace(tzinfo=None)


# --------------------------------------------------
# LIMPEZA DE JSON DA IA
# --------------------------------------------------

def limpar_json(texto: str):

    texto = re.sub(r"```json", "", texto)
    texto = re.sub(r"```", "", texto)

    texto = texto.strip()

    match = re.search(r"\{.*\}", texto, re.DOTALL)

    if match:
        return match.group()

    return texto


# --------------------------------------------------
# VALIDAÇÃO DE RESPOSTA
# --------------------------------------------------

def validar_resposta(resposta: dict):

    action = resposta.get("action")

    if not action:
        return {
            "action": "reply",
            "message": "Desculpa, pode repetir? 😊"
        }

    # proteção contra agendamento incompleto
    if action == "create_appointment":

        campos_obrigatorios = [
            "customer_name",
            "pet_name",
            "service",
            "datetime"
        ]

        for campo in campos_obrigatorios:

            if not resposta.get(campo):

                return {
                    "action": "reply",
                    "message": "Antes de finalizar o agendamento, preciso de mais algumas informações 😊"
                }

    return resposta


# --------------------------------------------------
# FUNÇÃO PRINCIPAL
# --------------------------------------------------

def chat_with_ai(conversation_history, new_message, customer_context=None):

    agora = agora_brasilia()

    data_atual = agora.strftime("%Y-%m-%d")
    hora_atual = agora.strftime("%H:%M")
    amanha = (agora + timedelta(days=1)).strftime("%Y-%m-%d")

    dias = [
        "segunda-feira",
        "terça-feira",
        "quarta-feira",
        "quinta-feira",
        "sexta-feira",
        "sábado",
        "domingo"
    ]

    dia_semana = dias[agora.weekday()]

    # --------------------------------------------------
    # CONTEXTO DO CLIENTE
    # --------------------------------------------------

    cliente_info = ""

    if customer_context:

        nome = customer_context.get("name")
        pets = customer_context.get("pets", [])
        total = customer_context.get("total_appointments", 0)

        if nome:
            cliente_info += f"\nCLIENTE: {nome}"

        if pets:

            cliente_info += "\nPETS CADASTRADOS:"

            for pet in pets:

                linha = f"\n- {pet['name']}"

                if pet.get("breed"):
                    linha += f" ({pet['breed']}"

                    if pet.get("weight"):
                        linha += f", {pet['weight']}kg"

                    linha += ")"

                cliente_info += linha

        if total > 0:
            cliente_info += f"\nCLIENTE RECORRENTE: sim ({total} atendimentos)"
        else:
            cliente_info += "\nCLIENTE RECORRENTE: não"

    # --------------------------------------------------
    # PROMPT DA IA
    # --------------------------------------------------

    system_prompt = f"""
Você é a Mari, atendente virtual do PetShop Amigo Fiel.

Você conversa com clientes no WhatsApp como uma atendente humana.

Seu objetivo é ajudar o cliente e agendar serviços para pets.

DATA ATUAL: {data_atual}
HORA ATUAL: {hora_atual}
DIA: {dia_semana}

{cliente_info}

--------------------------------------------------

ESTILO DE CONVERSA

Fale de forma natural como no WhatsApp.

Regras:

- use frases curtas
- 1 ou 2 frases por mensagem
- seja simpática
- seja acolhedora

Use emojis moderados:
🐾 😊 ✂️ 📅

Se souber o nome do cliente → use.

Exemplo:
"Oi João! 😊"

Se souber o nome do pet → use também.

--------------------------------------------------

REGRAS CRÍTICAS

Nunca invente horários disponíveis.

Sempre use:
check_availability

para buscar horários livres.

Nunca crie agendamento sem:

- nome do cliente
- nome do pet
- serviço
- data
- horário

Se faltar informação → pergunte.

--------------------------------------------------

HORÁRIO DE FUNCIONAMENTO

Segunda a sábado
09:00 às 18:00

Domingo fechado

--------------------------------------------------

SERVIÇOS

banho_simples
banho_tosa
tosa_higienica
consulta

--------------------------------------------------

IDENTIFICAÇÃO

"banho e tosa" → banho_tosa

"banho" → banho_simples

"higiênica" → tosa_higienica

"consulta"
"veterinário"

→ consulta

--------------------------------------------------

FLUXO

1 cliente quer agendar

2 descobrir serviço

3 perguntar data

4 buscar horários

5 cliente escolhe horário

6 coletar dados do pet

7 confirmar

8 criar agendamento

--------------------------------------------------

CONFIRMAÇÃO

Antes de criar agendamento envie:

🐾 Pet: [nome]
✂️ Serviço: [serviço]
📅 Data: [data]
🕐 Hora: [hora]

Pergunte:

"Está tudo certinho? 😊"

--------------------------------------------------

FORMATO DE RESPOSTA

Sempre JSON puro.

Sem markdown.

Exemplos:

{{"action":"reply","message":"mensagem"}}

{{"action":"check_availability","date":"{data_atual}","service":"banho_tosa"}}

{{"action":"create_appointment",
"customer_name":"João",
"pet_name":"Rex",
"pet_breed":"Golden Retriever",
"pet_weight":30,
"service":"banho_tosa",
"datetime":"{data_atual}T15:00:00",
"pickup_time":"18:00"
}}

{{"action":"list_appointments"}}

{{"action":"cancel_appointment","appointment_index":1}}

Responda APENAS com JSON.

"""

    # --------------------------------------------------
    # MENSAGENS
    # --------------------------------------------------

    messages = [{"role": "system", "content": system_prompt}]

    messages.extend(conversation_history[-14:])

    messages.append({
        "role": "user",
        "content": new_message
    })

    # --------------------------------------------------
    # CHAMADA DA IA
    # --------------------------------------------------

    try:

        response = client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            temperature=0.3,
            max_tokens=600
        )

        texto = response.choices[0].message.content.strip()

        texto = limpar_json(texto)

        try:

            resultado = json.loads(texto)

        except:

            resultado = {
                "action": "reply",
                "message": texto
            }

        resultado = validar_resposta(resultado)

        return resultado

    except Exception as e:

        return {
            "action": "reply",
            "message": "Tive um pequeno problema técnico 😅 pode repetir?"
        }


# --------------------------------------------------
# TESTE LOCAL
# --------------------------------------------------

def test_ai():

    history = []

    resposta = chat_with_ai(
        history,
        "Oi queria agendar banho pro meu cachorro"
    )

    print(resposta)


if __name__ == "__main__":
    test_ai()
    