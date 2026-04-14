from openai import OpenAI
from dotenv import load_dotenv
from datetime import datetime, timedelta
from typing import Optional
import pytz, os, json, re

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
BRASILIA = pytz.timezone("America/Sao_Paulo")


def agora_brasilia() -> datetime:
    return datetime.now(BRASILIA).replace(tzinfo=None)


def build_services_prompt(services: list) -> str:
    if not services:
        return "Nenhum servico cadastrado no momento."
    lines = []
    for s in services:
        price = f"R$ {s['price']/100:.2f}" if s.get("price") else "Gratis"
        desc  = f" | {s['description']}" if s.get("description") else ""
        lines.append(f'- chave="{s["key"]}" | nome="{s["name"]}" | {price} | {s["duration_min"]}min{desc}')
    return "\n".join(lines)


def build_hours_prompt(cfg: dict) -> str:
    short = {"0":"Seg","1":"Ter","2":"Qua","3":"Qui","4":"Sex","5":"Sab","6":"Dom"}
    full  = {"0":"segunda","1":"terca","2":"quarta","3":"quinta","4":"sexta","5":"sabado","6":"domingo"}
    open_days = [d.strip() for d in (cfg.get("open_days") or "0,1,2,3,4,5").split(",")]
    closed    = [full[d] for d in "0123456" if d not in open_days]
    names     = [short[d] for d in open_days if d in short]
    t = f"{', '.join(names)} das {cfg.get('open_time','09:00')} as {cfg.get('close_time','18:00')}."
    if closed:
        t += f" Fechado: {', '.join(closed)}."
    return t


def extract_json_object(text: str) -> Optional[str]:
    start = text.find("{")
    if start == -1:
        return None
    stack, in_str, esc = 0, False, False
    for i, ch in enumerate(text[start:], start):
        if in_str:
            if esc:   esc = False
            elif ch == "\\": esc = True
            elif ch == '"':  in_str = False
        else:
            if   ch == '"': in_str = True
            elif ch == '{': stack += 1
            elif ch == '}':
                stack -= 1
                if stack == 0:
                    return text[start:i+1]
    return None


# ── Configuração por tipo de negócio ─────────────────────────────────────────
BUSINESS_CONFIG = {
    "petshop": {
        "emoji": "🐾",
        "personality": "calorosa, simpatica e amante dos animais — como uma funcionaria do pet shop que conhece cada bichinho",
        "needs_subject": True,
        "subject_fields": "nome, raca e peso",
        "needs_pickup": True,
        "resumo_subject": True,
        "resumo_pickup": True,
        "campos_obrigatorios": "customer_name, pet_name, pet_breed, pet_weight, service, datetime, pickup_time",
    },
    "clinica": {
        "emoji": "🏥",
        "personality": "profissional, empatica e acolhedora — como recepcionista de clinica veterinaria experiente",
        "needs_subject": True,
        "subject_fields": "nome e especie/raca (peso se relevante)",
        "needs_pickup": False,
        "resumo_subject": True,
        "resumo_pickup": False,
        "campos_obrigatorios": "customer_name, pet_name, pet_breed, service, datetime",
    },
    "adocao": {
        "emoji": "❤️",
        "personality": "calorosa e apaixonada por animais — como voluntaria engajada em adocao responsavel",
        "needs_subject": True,
        "subject_fields": "nome e especie/raca do animal",
        "needs_pickup": False,
        "resumo_subject": True,
        "resumo_pickup": False,
        "campos_obrigatorios": "customer_name, pet_name, pet_breed, service, datetime",
    },
    "barbearia": {
        "emoji": "💈",
        "personality": "descontraida e parceira — como barbeiro amigo que ja conhece os clientes pelo nome",
        "needs_subject": False,
        "subject_fields": "",
        "needs_pickup": False,
        "resumo_subject": False,
        "resumo_pickup": False,
        "campos_obrigatorios": "customer_name, service, datetime",
    },
    "salao": {
        "emoji": "💅",
        "personality": "animada e acolhedora — como cabeleireira amiga sempre atualizada nas tendencias",
        "needs_subject": False,
        "subject_fields": "",
        "needs_pickup": False,
        "resumo_subject": False,
        "resumo_pickup": False,
        "campos_obrigatorios": "customer_name, service, datetime",
    },
    "estetica": {
        "emoji": "🌸",
        "personality": "elegante e atenciosa — como especialista em bem-estar que valoriza cada cliente",
        "needs_subject": False,
        "subject_fields": "",
        "needs_pickup": False,
        "resumo_subject": False,
        "resumo_pickup": False,
        "campos_obrigatorios": "customer_name, service, datetime",
    },
    "outro": {
        "emoji": "📅",
        "personality": "simpatica e prestativa — como boa recepcionista que conhece bem o negocio",
        "needs_subject": False,
        "subject_fields": "",
        "needs_pickup": False,
        "resumo_subject": False,
        "resumo_pickup": False,
        "campos_obrigatorios": "customer_name, service, datetime",
    },
}

def get_biz(business_type: str) -> dict:
    return BUSINESS_CONFIG.get(business_type, BUSINESS_CONFIG["outro"])


def build_resumo(biz: dict, subject: str, needs_address: bool, address_label: str) -> str:
    """Monta o template de resumo de acordo com as configurações do tenant."""
    lines = []
    if biz["resumo_subject"]:
        lines.append(f'{biz["emoji"]} {subject}: [nome] ([detalhe])')
    lines.append("👤 Cliente: [nome do cliente]")
    lines.append("✂️ Servico: [servico] — [preco]")
    lines.append("📅 [data] as [hora]")
    if biz["resumo_pickup"]:
        lines.append("🏠 Busca: [horario]")
    if needs_address:
        lines.append(f"📍 {address_label}: [endereco completo]")
    lines.append("\nTa certinho assim? 😊")
    return "\n".join(lines)


def build_create_example(biz: dict, svc_key: str, needs_address: bool) -> str:
    """Monta o exemplo de JSON create_appointment com pickup_address quando aplicável."""
    base = {
        "action": "create_appointment",
        "customer_name": "Joao",
        "service": svc_key,
        "datetime": "YYYY-MM-DDTHH:MM:00",
    }
    if biz["needs_subject"]:
        base["pet_name"]   = "Rex"
        base["pet_breed"]  = "Golden"
        base["pet_weight"] = 30.0
    else:
        base["pet_name"]   = None
        base["pet_breed"]  = None
        base["pet_weight"] = None
    base["pickup_time"]    = "HH:MM" if biz["needs_pickup"] else None
    base["pickup_address"] = "Rua Exemplo, 123 — Bairro" if needs_address else None
    return json.dumps(base, ensure_ascii=False)


def chat_with_ai(
    conversation_history: list,
    new_message: str,
    customer_context: dict = None,
    tenant_config: dict = None,
    services: list = None,
) -> dict:

    agora        = agora_brasilia()
    data_hoje    = agora.strftime("%Y-%m-%d")
    hora_agora   = agora.strftime("%H:%M")
    data_amanha  = (agora + timedelta(days=1)).strftime("%Y-%m-%d")
    dia_semana   = ["segunda","terca","quarta","quinta","sexta","sabado","domingo"][agora.weekday()]

    cfg            = tenant_config or {}
    attendant      = cfg.get("bot_attendant_name") or "Mari"
    biz_name       = cfg.get("bot_business_name") or cfg.get("display_name") or cfg.get("name") or "nosso estabelecimento"
    biz_type       = cfg.get("business_type") or "outro"
    subject        = cfg.get("subject_label") or "Cliente"
    subject_plural = cfg.get("subject_label_plural") or "Clientes"

    # ── Campos de endereço vindos do tenant_config ────────────────────────────
    needs_address = bool(cfg.get("needs_address", False))
    address_label = cfg.get("address_label") or "Endereço de busca"

    biz       = get_biz(biz_type)
    resumo    = build_resumo(biz, subject, needs_address, address_label)
    svc_key   = (services or [{}])[0].get("key", "servico") if services else "servico"
    ex_create = build_create_example(biz, svc_key, needs_address)

    hours_text    = build_hours_prompt(cfg)
    services_text = build_services_prompt(services or [])

    # ── Contexto do cliente ───────────────────────────────────────────────────
    ctx_lines, nome_conhecido = [], False
    if customer_context:
        nome = customer_context.get("name", "")
        if nome:
            nome_conhecido = True
            ctx_lines.append(f"NOME DO CLIENTE: {nome}")
        if customer_context.get("pets") and biz["needs_subject"]:
            ctx_lines.append(f"{subject_plural.upper()} CADASTRADOS:")
            for p in customer_context["pets"]:
                s = f"  - {p['name']}"
                if p.get("breed"): s += f" ({p['breed']}"
                if p.get("weight"): s += f", {p['weight']}kg"
                if p.get("breed"): s += ")"
                ctx_lines.append(s)
        n = customer_context.get("total_appointments", 0)
        ctx_lines.append(f"RECORRENTE: {'sim (' + str(n) + ' agendamentos)' if n > 0 else 'nao (primeira vez)'}")

    ctx_block   = "\n".join(ctx_lines) if ctx_lines else "Nenhum dado previo."
    nome_status = "JA SABEMOS O NOME" if nome_conhecido else "NOME DESCONHECIDO — pergunte antes de qualquer acao"

    # ── Regras específicas do negócio ─────────────────────────────────────────
    if biz["needs_subject"]:
        regra_subject = (
            f"COLETA DE DADOS DO {subject.upper()}: apos confirmar horario, colete {biz['subject_fields']} do {subject.lower()}."
        )
        campos_obrigatorios = biz["campos_obrigatorios"]
    else:
        regra_subject = (
            f"NAO pergunte sobre pet, raca, peso ou animal. "
            f"O cliente e o proprio sujeito. Campos pet_name/pet_breed/pet_weight devem ser null."
        )
        campos_obrigatorios = biz["campos_obrigatorios"]

    if needs_address:
        campos_obrigatorios += ", pickup_address"

    regra_campos = (
        f"Campos obrigatorios para create_appointment: {campos_obrigatorios}. "
        f"Nao crie o agendamento sem todos esses dados."
    )

    if biz["needs_pickup"]:
        regra_pickup = f"Pergunte o horario de busca (quando o cliente quer que busquem o {subject.lower()})."
    else:
        regra_pickup = "NAO pergunte horario de busca. pickup_time=null sempre."

    # ── Regra de endereço (condicional) ───────────────────────────────────────
    if needs_address:
        regra_address = (
            f"COLETA DE ENDERECO (OBRIGATORIA): apos confirmar o horario "
            f"(e horario de busca se aplicavel), pergunte o endereco completo do cliente. "
            f"Use o label '{address_label}' na pergunta. "
            f"Exemplo: 'Qual o {address_label.lower()}? 📍 (rua, numero e bairro)'. "
            f"Inclua no JSON: \"pickup_address\": \"[endereco informado]\". "
            f"Mostre no resumo como: 📍 {address_label}: [endereco]. "
            f"NUNCA crie o agendamento sem o endereco quando needs_address=true."
        )
    else:
        regra_address = (
            "NAO pergunte endereco ao cliente. pickup_address=null sempre."
        )

    system_prompt = f"""Voce e {attendant}, atendente virtual de {biz_name}.
Personalidade: {biz["personality"]}.
Converse de forma natural pelo WhatsApp — seja humana, nunca robotica.

=== CONTEXTO ATUAL ===
Data: {data_hoje} ({dia_semana}) | Hora: {hora_agora} | Amanha: {data_amanha}
{ctx_block}
Nome do cliente: {nome_status}

=== REGRAS ABSOLUTAS — NUNCA QUEBRE ===

REGRA 1 — NOME:
- Se nome DESCONHECIDO: a PRIMEIRA coisa e pedir o nome. Sem excecoes.
- Se o cliente mandar servico+data+hora tudo junto mas nome desconhecido: peca o nome E ja dispare check_availability em paralelo na mesma resposta.
- NUNCA crie agendamento sem saber o nome real do cliente.
- NUNCA use "[Nome do Cliente]" no resumo. Use o nome real coletado.

REGRA 2 — HORARIO ESPECIFICO (CRITICA):
- Se o cliente pediu um horario ESPECIFICO (ex: "as 10h", "as 13:00", "10 horas"):
  * Chame check_availability para VERIFICAR se esta disponivel
  * Se disponivel: confirme esse horario especifico e siga para o proximo passo
  * Se ocupado: informe e oferta alternativas proximas
  * NUNCA liste todos os horarios quando o cliente ja pediu um especifico
- Se o cliente NAO pediu horario especifico: chame check_availability e mostre os horarios disponiveis

REGRA 3 — NAO REPITA PERGUNTAS:
- Se o cliente ja respondeu um campo, use essa resposta. Nao pergunte de novo.
- Se falta apenas 1 dado, pergunte so esse dado em frase curta.
- Se ja tem servico+data+horario+nome: va direto para coleta de dados especificos (se necessario) ou resumo.

REGRA 4 — DADOS ESPECIFICOS DESTE NEGOCIO:
{regra_subject}
{regra_pickup}

REGRA 5 — ENDERECO:
{regra_address}

REGRA 6 — CAMPOS OBRIGATORIOS:
{regra_campos}

REGRA 7 — RESUMO E CONFIRMACAO:
- Sempre mostre o resumo completo e peca confirmacao ANTES de criar.
- Modelo do resumo:
{resumo}

REGRA 8 — ESCOPO:
- Fale SOMENTE sobre servicos deste estabelecimento.
- Se o cliente falar de outro assunto, responda educadamente que so faz agendamentos.

=== TOM E PERSONALIDADE ===
- Use o nome do cliente quando souber: "Oi Joao!", "Perfeito, Joao!"
- Emojis naturais, sem exagero (2-3 por mensagem)
- Clientes recorrentes: demonstre que reconhece ("Que saudade! 😊")
- Quando verificar agenda: "Um segundinho! 🗓️"
- Linguagem: "ta", "pra", "vc", "tbm" — natural mas sem exagerar
- Seja direta: se falta apenas 1 dado, pergunte so esse dado

=== FERIADOS 2026 ===
01/01 | 16-17/02 Carnaval | 03/04 Sexta Santa | 21/04 Tiradentes
01/05 | 04/06 Corpus Christi | 07/09 Independencia | 12/10 N.Sra.Aparecida
02/11 Finados | 15/11 Republica | 25/12 Natal

=== FUNCIONAMENTO ===
{hours_text}

=== SERVICOS (use EXATAMENTE as chaves) ===
{services_text}

=== ACOES — RESPONDA SEMPRE EM JSON PURO ===

Verificar disponibilidade (cliente NAO pediu horario especifico):
{{"action":"check_availability","date":"YYYY-MM-DD","service":"{svc_key}"}}

Verificar horario especifico (cliente pediu "as 10h", "as 13:00" etc):
{{"action":"check_availability","date":"YYYY-MM-DD","service":"{svc_key}","requested_time":"HH:MM"}}

Criar agendamento:
{ex_create}

Listar agendamentos do cliente:
{{"action":"list_appointments"}}

Cancelar agendamento:
{{"action":"cancel_appointment","appointment_index":1}}

Resposta normal:
{{"action":"reply","message":"texto aqui"}}

=== REGRAS DO JSON ===
- SEMPRE JSON puro — sem markdown, sem texto fora do JSON, sem aspas extras
- "service": use APENAS as chaves listadas nos servicos
- "datetime": formato exato "YYYY-MM-DDTHH:MM:00"
- "pickup_address": endereco completo informado pelo cliente, ou null se nao aplicavel
- Campos null quando nao aplicavel ao tipo de negocio
"""

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(conversation_history[-20:])
    messages.append({"role": "user", "content": new_message})

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=messages,
        temperature=0.3,
        max_tokens=900,
    )

    raw = response.choices[0].message.content.strip()
    raw = re.sub(r"```json\s*", "", raw)
    raw = re.sub(r"```\s*", "", raw).strip()

    json_str = extract_json_object(raw)
    if json_str:
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            pass
    return {"action": "reply", "message": raw}