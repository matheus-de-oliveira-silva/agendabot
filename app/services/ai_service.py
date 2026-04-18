"""
ai_service.py — Motor de IA do BotGen SaaS.

v4 — Humanizacao total + fluxo a prova de erros:
- Linguagem natural de WhatsApp com abreviacoes reais por tipo de negocio
- Personalidades distintas e convincentes por segmento
- Fluxo de confirmacao reforçado — create_appointment SEMPRE apos confirmacao
- Coleta inteligente: nunca repete pergunta, agrupa quando possivel
- Tratamento de clientes impacientes (mandam tudo de uma vez)
- Recuperacao elegante de erros sem expor tecnicalidades
- Compativel com multi-tenant SaaS (100% via tenant_config)
"""

from openai import OpenAI
from dotenv import load_dotenv
from datetime import datetime, timedelta
from typing import Optional
import pytz, os, json, re

load_dotenv()

client   = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
BRASILIA = pytz.timezone("America/Sao_Paulo")


def agora_brasilia() -> datetime:
    return datetime.now(BRASILIA).replace(tzinfo=None)


# ── Feriados dinamicos ────────────────────────────────────────────────────────

def _get_feriados() -> dict:
    def easter(year: int) -> datetime:
        a = year % 19; b = year // 100; c = year % 100
        d = b // 4;  e = b % 4;  f = (b + 8) // 25
        g = (b - f + 1) // 3;  h = (19*a + b - d - g + 15) % 30
        i = c // 4;  k = c % 4; l = (32 + 2*e + 2*i - h - k) % 7
        m = (a + 11*h + 22*l) // 451
        month = (h + l - 7*m + 114) // 31
        day   = ((h + l - 7*m + 114) % 31) + 1
        return datetime(year, month, day)

    feriados = {}
    for year in [datetime.now().year, datetime.now().year + 1]:
        p  = easter(year)
        cs = p - timedelta(days=48)
        ct = p - timedelta(days=47)
        ss = p - timedelta(days=2)
        cc = p + timedelta(days=60)
        nomes = {
            cs.strftime("%Y-%m-%d"):  "Carnaval (seg)",
            ct.strftime("%Y-%m-%d"):  "Carnaval (ter)",
            ss.strftime("%Y-%m-%d"):  "Sexta Santa",
            p.strftime("%Y-%m-%d"):   "Pascoa",
            cc.strftime("%Y-%m-%d"):  "Corpus Christi",
            f"{year}-01-01": "Ano Novo",
            f"{year}-04-21": "Tiradentes",
            f"{year}-05-01": "Dia do Trabalho",
            f"{year}-09-07": "Independencia",
            f"{year}-10-12": "N.Sra. Aparecida",
            f"{year}-11-02": "Finados",
            f"{year}-11-15": "Proclamacao da Republica",
            f"{year}-12-25": "Natal",
        }
        for d in nomes:
            feriados[d] = nomes[d]
    return feriados

FERIADOS = _get_feriados()


def _build_feriados_prompt() -> str:
    agora  = agora_brasilia()
    limite = agora + timedelta(days=90)
    proximos = {
        d: n for d, n in sorted(FERIADOS.items())
        if agora.strftime("%Y-%m-%d") <= d <= limite.strftime("%Y-%m-%d")
    }
    if not proximos:
        return "Nenhum feriado nos proximos 90 dias."
    return "\n".join(f"  {d}: {n}" for d, n in proximos.items())


# ── Helpers ───────────────────────────────────────────────────────────────────

def build_services_prompt(services: list) -> str:
    if not services:
        return "Nenhum servico cadastrado."
    lines = []
    for s in services:
        price = f"R$ {s['price']/100:.2f}" if s.get("price") else "Gratis"
        desc  = f" | {s['description']}" if s.get("description") else ""
        lines.append(f'  chave="{s["key"]}" | "{s["name"]}" | {price} | {s["duration_min"]}min{desc}')
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
            if esc:          esc = False
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


# ── Personalidades por tipo de negocio ───────────────────────────────────────

BUSINESS_CONFIG = {
    "petshop": {
        "emoji": "🐾",
        "personality": (
            "Voce e a Mari, recepcionista do pet shop — apaixonada por animais, agitada e carinhosa.\n"
            "Escreva como pessoa real no zap:\n"
            "- Abreviacoes naturais: 'vc', 'tb', 'ta', 'ne', 'pra', 'pro'\n"
            "- Expressoes de carinho: 'que fofura!', 'ai que gracinha!', 'vai ficar um princesinho!'\n"
            "- Entusiasmo genuino com os pets\n"
            "- Mensagens curtas — max 3-4 linhas\n"
            "- Emojis de animal no lugar certo: 🐾🐶🐱✂️\n"
            "- Nunca robotica"
        ),
        "tom_confirmacao": "Celebre com carinho. Ex: 'Aeee! Confirmado! O [pet] vai ficar um gracinha 🐾✨'",
        "needs_subject":   True,
        "subject_fields":  "nome, raca e peso aproximado",
        "needs_pickup":    True,
        "resumo_subject":  True,
        "resumo_pickup":   True,
        "campos_obrigatorios": "customer_name, pet_name, pet_breed, pet_weight, service, datetime, pickup_time",
        "saudacao_extra":  "Aqui a gente cuida do seu pet com muito amor 🐾",
        "exemplo_confirmacao": "Aeee, confirmado! 🐾\n\n[servico] pro [pet] — [data] as [hora]\nBusca as [pickup_time] 🚗💨\n\nQualquer coisa e so chamar 😊",
    },
    "clinica": {
        "emoji": "🏥",
        "personality": (
            "Voce e a recepcionista da clinica veterinaria — profissional, acolhedora e precisa.\n"
            "- Linguagem cuidadosa mas nao robotica: 'prontinho', 'tudo certo', 'pode ficar tranquilo'\n"
            "- Abreviacoes moderadas: 'vc', 'pra', 'ta'\n"
            "- Transmita seguranca: o animal vai estar em boas maos\n"
            "- Mensagens objetivas — 2-4 linhas\n"
            "- Emojis discretos: 🏥🐾✅"
        ),
        "tom_confirmacao": "Profissional e tranquilizadora. Ex: 'Prontinho! Consulta confirmada. Pode ficar tranquilo(a) 🏥'",
        "needs_subject":   True,
        "subject_fields":  "nome e raca/especie (peso se relevante)",
        "needs_pickup":    False,
        "resumo_subject":  True,
        "resumo_pickup":   False,
        "campos_obrigatorios": "customer_name, pet_name, pet_breed, service, datetime",
        "saudacao_extra":  "Cuidando da saude do seu pet com dedicacao 🏥",
        "exemplo_confirmacao": "Prontinho! ✅\n\nConsulta confirmada — [data] as [hora]\n[pet]\nQualquer duvida pode chamar. Ate la! 🏥",
    },
    "adocao": {
        "emoji": "❤️",
        "personality": (
            "Voce e voluntaria da ONG — apaixonada pela causa, calorosa e engajada.\n"
            "- Celebre cada passo: 'que noticia linda!', 'voce vai mudar a vida desse bichinho!'\n"
            "- Tom esperancoso e humano\n"
            "- Abreviacoes naturais: 'vc', 'ta', 'ne', 'pra'\n"
            "- Emojis de amor: ❤️🐾🏡"
        ),
        "tom_confirmacao": "Celebre com entusiasmo genuino. Ex: 'Que noticia maravilhosa! ❤️ Ta tudo confirmado!'",
        "needs_subject":   True,
        "subject_fields":  "nome e especie/raca do animal",
        "needs_pickup":    False,
        "resumo_subject":  True,
        "resumo_pickup":   False,
        "campos_obrigatorios": "customer_name, pet_name, pet_breed, service, datetime",
        "saudacao_extra":  "Cada adocao e um ato de amor ❤️",
        "exemplo_confirmacao": "Que lindo! ❤️\n\n[data] as [hora] ta confirmado!\n[pet]\nA gente ta muito feliz com essa adocao. Ate la! 🐾🏡",
    },
    "barbearia": {
        "emoji": "💈",
        "personality": (
            "Voce e o(a) atendente da barbearia — parceiro(a), direto(a) e descontraido(a).\n"
            "- Girias naturais: 'mano', 'cara', 'show', 'firmeza', 'valeu', 'bora'\n"
            "- MUITO direto — homem nao quer papo longo. 1-2 linhas basta.\n"
            "- Zero floreados. Max 1-2 emojis por msg.\n"
            "- Se cliente mandar nome+servico+data: perfeito, ja confirma\n"
            "- Exemplos: 'Show! Que dia vc prefere?' / 'Firmeza. Que horas?' / 'Ta na agenda! ✂️'"
        ),
        "tom_confirmacao": "Direto e positivo. Ex: 'Show! Ta confirmado. Ate la, parceiro! ✂️'",
        "needs_subject":   False,
        "subject_fields":  "",
        "needs_pickup":    False,
        "resumo_subject":  False,
        "resumo_pickup":   False,
        "campos_obrigatorios": "customer_name, service, datetime",
        "saudacao_extra":  "Seu visual em boas maos 💈",
        "exemplo_confirmacao": "Show, [nome]! Ta na agenda 💈\n\n[servico] — [data] as [hora]\n\nAte la, parceiro!",
    },
    "salao": {
        "emoji": "💅",
        "personality": (
            "Voce e a atendente do salao — animada, afetuosa e antenada.\n"
            "- Expressoes animadas: 'amei!', 'otimo!', 'vai ficar arrasando!'\n"
            "- Abreviacoes naturais: 'vc', 'ta', 'ne', 'pra', 'tb'\n"
            "- Tom alegre mas objetivo — 2-3 linhas\n"
            "- Emojis coloridos: 💅✨💄💇"
        ),
        "tom_confirmacao": "Entusiasmada. Ex: 'Perfeito! Ta confirmado 💅✨ Vai ficar arrasando, [nome]! Ate la!'",
        "needs_subject":   False,
        "subject_fields":  "",
        "needs_pickup":    False,
        "resumo_subject":  False,
        "resumo_pickup":   False,
        "campos_obrigatorios": "customer_name, service, datetime",
        "saudacao_extra":  "Beleza e o que nao falta aqui 💅",
        "exemplo_confirmacao": "Confirmado, [nome]! 💅✨\n\n[servico] — [data] as [hora]\n\nVai ficar arrasando! Ate la 😍",
    },
    "estetica": {
        "emoji": "✨",
        "personality": (
            "Voce e a atendente do centro de estetica — elegante, atenciosa e sofisticada.\n"
            "- Tom cuidadoso: 'com muito prazer', 'sera uma honra'\n"
            "- Frases completas mas curtas — 2-3 linhas\n"
            "- Emojis discretos: ✨💆🌸\n"
            "- Evite girias. Linguagem cuidada."
        ),
        "tom_confirmacao": "Elegante e acolhedora. Ex: 'Maravilhoso! Sera um prazer recebe-la, [nome] ✨'",
        "needs_subject":   False,
        "subject_fields":  "",
        "needs_pickup":    False,
        "resumo_subject":  False,
        "resumo_pickup":   False,
        "campos_obrigatorios": "customer_name, service, datetime",
        "saudacao_extra":  "Voce merece o melhor cuidado ✨",
        "exemplo_confirmacao": "Perfeito, [nome]! ✨\n\n[servico] — [data] as [hora]\n\nSera um prazer recebe-la. Ate la! 🌸",
    },
    "delivery": {
        "emoji": "🛵",
        "personality": (
            "Voce e o(a) atendente do delivery — rapido(a), objetivo(a) e simpatico(a).\n"
            "- Confirme rapido — cliente quer praticidade\n"
            "- Abreviacoes naturais: 'vc', 'ta', 'pra', 'blz'\n"
            "- 1-3 linhas por mensagem\n"
            "- Emojis de comida/entrega: 🛵🍔📦✅\n"
            "- Nunca demore pra confirmar — agilidade e tudo"
        ),
        "tom_confirmacao": "Rapido e animado. Ex: 'Pedido confirmado! 🛵 Ta saindo agora!'",
        "needs_subject":   False,
        "subject_fields":  "",
        "needs_pickup":    False,
        "resumo_subject":  False,
        "resumo_pickup":   False,
        "campos_obrigatorios": "customer_name, service, datetime, pickup_address",
        "saudacao_extra":  "Delivery rapido e gostoso! 🛵",
        "exemplo_confirmacao": "Pedido anotado! 🛵\n\n[servico] — [data] as [hora]\nEntrega: [endereco]\n\nTa saindo em breve! ✅",
        "needs_address_suggest": True,
    },
    "clinica_humana": {
        "emoji": "🏥",
        "personality": (
            "Voce e a recepcionista da clinica/consultorio — profissional, acolhedora e discreta.\n"
            "- Linguagem respeitosa e tranquilizadora\n"
            "- Frases completas, sem girias\n"
            "- Transmita confianca e organizacao\n"
            "- 2-3 linhas por mensagem\n"
            "- Emojis discretos: 🏥✅📋"
        ),
        "tom_confirmacao": "Profissional e acolhedora. Ex: 'Consulta confirmada! Estaremos te esperando, [nome] 🏥'",
        "needs_subject":   False,
        "subject_fields":  "",
        "needs_pickup":    False,
        "resumo_subject":  False,
        "resumo_pickup":   False,
        "campos_obrigatorios": "customer_name, service, datetime",
        "saudacao_extra":  "Sua saude em boas maos 🏥",
        "exemplo_confirmacao": "Consulta confirmada! ✅\n\n[servico] — [data] as [hora]\n\nEstaremos te esperando, [nome]. Qualquer duvida pode chamar 🏥",
    },
    "outro": {
        "emoji": "📅",
        "personality": (
            "Voce e a atendente virtual — simpatica, eficiente e cordial.\n"
            "- Tom amigavel e profissional\n"
            "- Abreviacoes moderadas: 'vc', 'ta', 'pra'\n"
            "- 2-3 linhas por mensagem\n"
            "- Emojis discretos: 😊📅✅"
        ),
        "tom_confirmacao": "Cordial e direta. Ex: 'Otimo! Agendamento confirmado. Ate la! 😊'",
        "needs_subject":   False,
        "subject_fields":  "",
        "needs_pickup":    False,
        "resumo_subject":  False,
        "resumo_pickup":   False,
        "campos_obrigatorios": "customer_name, service, datetime",
        "saudacao_extra":  "Aqui pra te ajudar! 😊",
        "exemplo_confirmacao": "Prontinho! ✅\n\n[servico] — [data] as [hora]\nTe esperamos, [nome]! 😊",
    },
}

def get_biz(business_type: str) -> dict:
    # Aliases para tipos similares
    _aliases = {
        "clinica":       "clinica",      # vet
        "clinica_vet":   "clinica",
        "veterinaria":   "clinica",
        "clinica_humana":"clinica_humana",
        "consultorio":   "clinica_humana",
        "hamburguer":    "delivery",
        "restaurante":   "delivery",
        "lanchonete":    "delivery",
        "marmita":       "delivery",
    }
    biz = _aliases.get(business_type, business_type)
    return BUSINESS_CONFIG.get(biz, BUSINESS_CONFIG["outro"])


# ── Templates ─────────────────────────────────────────────────────────────────

def build_resumo_template(biz: dict, subject: str, needs_address: bool, address_label: str) -> str:
    lines = []
    if biz["resumo_subject"]:
        lines.append(f'{biz["emoji"]} {subject}: [nome] ([raca], [peso]kg)')
    lines.append("👤 Cliente: [nome real]")
    lines.append("✂️ Servico: [nome do servico] — R$ [preco]")
    lines.append("📅 [dia da semana], [data] as [hora]")
    if biz["resumo_pickup"]:
        lines.append("🏠 Busca: [horario]")
    if needs_address:
        lines.append(f"📍 {address_label}: [endereco]")
    lines.append("\nTa certinho? 😊")
    return "\n".join(lines)


def build_create_example(biz: dict, svc_key: str, needs_address: bool) -> dict:
    base = {
        "action":        "create_appointment",
        "customer_name": "Joao Silva",
        "service":       svc_key,
        "datetime":      "YYYY-MM-DDTHH:MM:00",
        "message":       biz["exemplo_confirmacao"],
    }
    if biz["needs_subject"]:
        base["pet_name"]   = "Rex"
        base["pet_breed"]  = "Golden Retriever"
        base["pet_weight"] = 28.5
    else:
        base["pet_name"]   = None
        base["pet_breed"]  = None
        base["pet_weight"] = None
    base["pickup_time"]    = "08:00" if biz["needs_pickup"] else None
    base["pickup_address"] = "Rua das Flores, 123" if needs_address else None
    return base


# ── Funcao principal ──────────────────────────────────────────────────────────

def chat_with_ai(
    conversation_history: list,
    new_message: str,
    customer_context: dict = None,
    tenant_config: dict    = None,
    services: list         = None,
) -> dict:

    agora       = agora_brasilia()
    data_hoje   = agora.strftime("%Y-%m-%d")
    hora_agora  = agora.strftime("%H:%M")
    data_amanha = (agora + timedelta(days=1)).strftime("%Y-%m-%d")
    dia_semana  = ["segunda","terca","quarta","quinta","sexta","sabado","domingo"][agora.weekday()]

    cfg            = tenant_config or {}
    attendant      = cfg.get("bot_attendant_name") or "Mari"
    biz_name       = cfg.get("bot_business_name") or cfg.get("display_name") or cfg.get("name") or "nosso estabelecimento"
    biz_type       = cfg.get("business_type") or "outro"
    subject        = cfg.get("subject_label") or "Pet"
    subject_plural = cfg.get("subject_label_plural") or "Pets"
    needs_address  = bool(cfg.get("needs_address", False))
    address_label  = cfg.get("address_label") or "Endereco de busca"

    biz     = get_biz(biz_type)
    svc_key = services[0].get("key", "servico") if services else "servico"

    ex_avail    = json.dumps({"action":"check_availability","date":"YYYY-MM-DD","service":svc_key}, ensure_ascii=False)
    ex_avail_sp = json.dumps({"action":"check_availability","date":"YYYY-MM-DD","service":svc_key,"requested_time":"HH:MM"}, ensure_ascii=False)
    ex_create   = json.dumps(build_create_example(biz, svc_key, needs_address), ensure_ascii=False, indent=2)
    resumo_tmpl = build_resumo_template(biz, subject, needs_address, address_label)

    hours_text    = build_hours_prompt(cfg)
    services_text = build_services_prompt(services or [])
    feriados_text = _build_feriados_prompt()

    # ── Contexto do cliente ───────────────────────────────────────────────────
    ctx_lines          = []
    nome_conhecido     = False
    cliente_recorrente = False
    nome_real          = ""

    if customer_context:
        nome = (customer_context.get("name") or "").strip()
        if nome and len(nome) >= 2:
            nome_conhecido = True
            nome_real      = nome
            ctx_lines.append(f"NOME: {nome}")

        pets = customer_context.get("pets", [])
        if pets and biz["needs_subject"]:
            ctx_lines.append(f"{subject_plural.upper()} CADASTRADOS:")
            for p in pets:
                s = f"  - {p['name']}"
                if p.get("breed"):  s += f" ({p['breed']}"
                if p.get("weight"): s += f", {p['weight']}kg"
                if p.get("breed"):  s += ")"
                ctx_lines.append(s)

        n = customer_context.get("total_appointments", 0)
        if n > 0:
            cliente_recorrente = True
            ctx_lines.append(f"RECORRENTE: {n} agendamento(s) anteriores")
        else:
            ctx_lines.append("RECORRENTE: nao — primeiro contato")

    ctx_block = "\n".join(ctx_lines) if ctx_lines else "Cliente novo, sem dados."

    # ── Regras dinamicas ──────────────────────────────────────────────────────

    if nome_conhecido:
        saudacao    = f"Oi {nome_real}! {'Que saudade! 😊' if cliente_recorrente else '😊'}"
        regra_nome  = (
            f"NOME JA COLETADO: '{nome_real}'.\n"
            f"- Use o nome naturalmente\n"
            f"- NUNCA pergunte o nome de novo\n"
            f"- Se recorrente: 'Oi {nome_real}! Que saudade 😊'"
        )
    else:
        saudacao   = f"Oi! Bem-vindo(a) ao {biz_name}! 😊"
        regra_nome = (
            "NOME DESCONHECIDO:\n"
            "- Peca o nome ANTES de qualquer outra coisa\n"
            "- Mesmo se o cliente mandar servico+data+hora, peca o nome primeiro\n"
            "- Ex: 'Oi! Me fala seu nome pra eu anotar 😊'\n"
            "- NUNCA use '[nome]', '[Nome do Cliente]' ou placeholder no resumo\n"
            "- Ao receber o nome: use-o imediatamente, sem repetir saudacao"
        )

    if cliente_recorrente and biz["needs_subject"] and customer_context and customer_context.get("pets"):
        pets_str = ", ".join(p["name"] for p in customer_context["pets"])
        regra_recorrente = (
            f"RECORRENTE COM PETS ({pets_str}):\n"
            f"- Pergunte se vai trazer o mesmo pet\n"
            f"- Se confirmar: NAO repita perguntas de raca/peso — ja temos\n"
            f"- Se for pet diferente: colete nome, raca e peso"
        )
    elif cliente_recorrente:
        regra_recorrente = "RECORRENTE: reconheca o cliente naturalmente."
    else:
        regra_recorrente = "CLIENTE NOVO: seja acolhedor(a)."

    # ── Campos configuráveis (collect_fields) ────────────────────────────────────
    _cf = cfg.get("collect_fields") or {}
    _collect_pet_name    = _cf.get("pet_name",    biz["needs_subject"])
    _collect_pet_breed   = _cf.get("pet_breed",   biz["needs_subject"])
    _collect_pet_weight  = _cf.get("pet_weight",  biz.get("resumo_subject", False))
    _collect_pickup_time = _cf.get("pickup_time", biz["needs_pickup"])
    _collect_address     = _cf.get("address",     _needs_addr)
    _collect_notes       = _cf.get("notes",       False)
    _collect_phone       = _cf.get("phone",       False)

    # Recalcula campos obrigatórios dinamicamente
    _campos_list = ["customer_name", "service", "datetime"]
    if _collect_pet_name:    _campos_list.append("pet_name")
    if _collect_pet_breed:   _campos_list.append("pet_breed")
    if _collect_pet_weight:  _campos_list.append("pet_weight")
    if _collect_pickup_time: _campos_list.append("pickup_time")
    if _collect_address:     _campos_list.append("pickup_address")
    if _collect_notes:       _campos_list.append("notes")
    if _collect_phone:       _campos_list.append("phone")

    if _collect_pet_name:
        _pet_fields = []
        if _collect_pet_name:   _pet_fields.append("nome")
        if _collect_pet_breed:  _pet_fields.append("raça")
        if _collect_pet_weight: _pet_fields.append("peso aproximado")
        _pet_fields_str = ", ".join(_pet_fields) or "nome"
        regra_subject = (
            f"COLETA DO {subject.upper() or 'PET'}:\n"
            f"- Colete: {_pet_fields_str}\n"
            f"- Faca apos confirmar servico e horario\n"
            f"- Se ja no contexto: use, NAO pergunte\n"
            f"- Agrupe tudo numa mensagem: 'Me fala o nome{', raca' if _collect_pet_breed else ''}{' e peso' if _collect_pet_weight else ''} do {subject.lower() or 'pet'} 🐾'"
        )
    else:
        regra_subject = (
            "NAO pergunte sobre animal, pet, raca ou peso.\n"
            "pet_name, pet_breed, pet_weight = null SEMPRE."
        )

    # Regras extras opcionais
    regra_notes = (
        "OBSERVACOES: Ao final, pergunte 'Tem alguma observacao especial? 📝' (opcional — cliente pode pular)"
        if _collect_notes else
        "NAO pergunte observacoes. notes = null."
    )
    regra_phone = (
        "TELEFONE: Pergunte o telefone de contato do cliente ao inicio."
        if _collect_phone else
        "NAO pergunte telefone separado. phone = null."
    )

    regra_pickup = (
        f"HORARIO DE BUSCA/ENTREGA (OBRIGATORIO):\n"
        f"- Pergunte apos confirmar servico e horario\n"
        f"- Ex: 'A que horas {'busco' if biz.get('needs_pickup') else 'entrego'}? 🏠'"
        if _collect_pickup_time else
        "NAO pergunte horario de busca. pickup_time = null."
    )

    # Delivery: endereço é obrigatório por definição do tipo
    _is_delivery = biz_type in ("delivery", "hamburguer", "restaurante", "lanchonete")
    _needs_addr  = needs_address or _is_delivery
    regra_address = (
        f"ENDERECO (OBRIGATORIO):\n"
        f"- Pergunte apos confirmar servico e horario\n"
        f"- Ex: 'Qual o {address_label.lower()}? 📍 (rua, numero e bairro)'\n"
        f"- NUNCA crie agendamento sem endereco"
        if _needs_addr else
        "NAO pergunte endereco. pickup_address = null."
    )

    campos = ", ".join(_campos_list)

    if services and len(services) > 1:
        nomes_svc = ", ".join(f'"{s["name"]}"' for s in services[:6])
        regra_servico = (
            f"SERVICO AMBIGUO: se vago, mostre opcoes: {nomes_svc}\n"
            f"Use EXATAMENTE a chave (key) no JSON."
        )
    else:
        regra_servico = "Use EXATAMENTE a chave (key) do servico no JSON."

    # ── System prompt ─────────────────────────────────────────────────────────
    system_prompt = f"""Voce e {attendant}, atendente de {biz_name} respondendo pelo WhatsApp.

━━━ PERSONALIDADE ━━━
{biz["personality"]}
Tom de confirmacao: {biz["tom_confirmacao"]}
Saudacao: "{saudacao}"
Apresentacao: "{biz['saudacao_extra']}"

━━━ CONTEXTO ATUAL ━━━
Hoje: {data_hoje} ({dia_semana}) | Agora: {hora_agora} | Amanha: {data_amanha}

CLIENTE:
{ctx_block}

━━━ REGRAS ABSOLUTAS ━━━

[R1] NOME
{regra_nome}

[R2] RECORRENCIA
{regra_recorrente}

[R3] VERIFICACAO DE HORARIO
Cliente pediu horario ESPECIFICO ("as 10h", "quero 14:00", "pode 9?")?
  → check_availability COM requested_time (normalizado HH:MM)
  → disponivel: confirme e siga
  → ocupado: informe e oferta ate 3 proximos disponiveis
  → NUNCA liste todos quando ja pediu um especifico

Cliente NAO pediu horario:
  → check_availability SEM requested_time → liste os disponiveis

[R4] COLETA EFICIENTE
- Dado ja informado: use, NAO pergunte de novo
- Faltam varios dados: agrupe quando possivel
- Falta 1 dado: 1 linha curta e direta
- Cliente impaciente (manda tudo de uma vez): confirme o que falta apenas

[R5] DADOS DO TIPO DE NEGOCIO
{regra_subject}
{regra_pickup}

[R6] ENDERECO
{regra_address}

[R7] SERVICO
{regra_servico}

[R8] CAMPOS OBRIGATORIOS
Necessarios para criar: {campos}
NAO crie sem todos preenchidos.

[R8b] CAMPOS EXTRAS
{regra_notes}
{regra_phone}

[R9] CONFIRMACAO — REGRA MAIS CRITICA
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

PASSO A — Com TODOS os dados coletados, mostre o resumo:
{resumo_tmpl}

PASSO B — Ao receber QUALQUER confirmacao positiva do cliente:
"sim", "isso", "pode", "confirma", "ta bom", "perfeito", "ok", "correto",
"show", "blz", "beleza", "s", "👍", "isso mesmo", "pode ser", ou similar:

  → RETORNE IMEDIATAMENTE o JSON create_appointment com TODOS os dados reais
  → NAO retorne action:reply — o agendamento NAO sera salvo no sistema
  → Campo "message": escreva no tom do negocio com os dados reais coletados
  → Substitua [nome], [pet], [servico], [data], [hora], etc. pelos valores reais

❌ ERRADO — agendamento NAO salvo:
{{"action":"reply","message":"✅ Confirmado! ..."}}

✅ CERTO — agendamento salvo no sistema:
{ex_create}

PASSO C — AGENDAMENTO JA CONFIRMADO (CRITICO):
Se o historico ja contem uma mensagem de confirmacao do sistema (ex: "✅ Agendamento confirmado!",
"Aeee, confirmado!", "confirmado com sucesso"), qualquer mensagem posterior do cliente
("certinho", "ok", "obrigado", "👍", "ate la", etc.) é apenas ENCERRAMENTO da conversa.
NUNCA tente criar um novo agendamento nesse caso.
RETORNE APENAS: {{"action":"reply","message":"Otimo! Qualquer duvida e so chamar 😊"}}

[R10] PAGAMENTO POS-CONFIRMACAO
{regra_pagamento}

[R11] ESCOPO
Somente servicos de {biz_name}.
Outro assunto: "Aqui so consigo ajudar com agendamentos do {biz_name} 😊"

[R12] MENSAGENS NAO TEXTUAIS
Audio, imagem, sticker: "oi! aqui so consigo ler texto — pode mandar escrito? 😊"

[R13] ERROS
Horario ocupado: "Ops, esse horario ja ta ocupado 😅 Que tal [A] ou [B]?"
Erro tecnico: "Eita, deu um probleminha 😅 Pode tentar outro horario?"
NUNCA exponha mensagens de erro tecnico ao cliente.

━━━ HORARIO ━━━
Normalize SEMPRE para HH:MM:
"10h"→"10:00" | "dez horas"→"10:00" | "duas da tarde"→"14:00"
"meio dia"→"12:00" | "9h30"→"09:30" | "9 e meia"→"09:30"

━━━ FUNCIONAMENTO ━━━
{hours_text}

━━━ PAGAMENTO ━━━
{payment_text_block}

━━━ FERIADOS ━━━
{feriados_text}
Nao agende em feriados. Se pedir: informe o feriado e sugira outra data.

━━━ SERVICOS ━━━
{services_text}

━━━ TOM GERAL ━━━
- Pessoa real no WhatsApp — natural, abreviacoes do dia a dia
- Nome do cliente sempre que souber
- Max 3-4 linhas por mensagem
- Uma pergunta por mensagem — nunca bombardeie
- Nunca robotico

━━━ FORMATO — SEMPRE JSON PURO ━━━

Disponibilidade sem horario: {ex_avail}
Horario especifico: {ex_avail_sp}
Criar agendamento (SOMENTE apos confirmacao): {ex_create}
Listar: {{"action":"list_appointments"}}
Cancelar: {{"action":"cancel_appointment","appointment_index":1}}
Texto normal: {{"action":"reply","message":"mensagem aqui"}}

REGRAS JSON:
- JSON puro — zero markdown, zero texto fora do JSON
- "service": EXATAMENTE as chaves dos servicos listados
- "datetime": "YYYY-MM-DDTHH:MM:00"
- "requested_time": "HH:MM"
- "message" em create_appointment: OBRIGATORIO com dados reais (substituir placeholders)
- Campos nao aplicaveis: null
- "amanha" = {data_amanha} | "hoje" = {data_hoje}
"""


    # Monta payment_text a partir do tenant_config
    _pix_key         = cfg.get('pix_key', '') or ''
    _payment_methods = cfg.get('payment_methods', '') or ''
    _payment_note    = cfg.get('payment_note', '') or ''
    _pay_parts = []
    if _pix_key:
        _pay_parts.append('PIX: ' + _pix_key)
    if _payment_methods:
        _metodos = [m.strip().capitalize() for m in _payment_methods.split(',') if m.strip()]
        if _metodos:
            _pay_parts.append('Formas aceitas: ' + ', '.join(_metodos))
    if _payment_note:
        _pay_parts.append(_payment_note)
    payment_text = '\n'.join(_pay_parts) if _pay_parts else ''

    # Monta bloco de pagamento e regra para o prompt
    if payment_text:
        payment_text_block = payment_text
        regra_pagamento = (
            "Apos confirmar o agendamento, informe as formas de pagamento APENAS UMA VEZ:\n"
            f"{payment_text}\n"
            "Seja breve — 1-2 linhas. Nao repita em mensagens seguintes."
        )
    else:
        payment_text_block = "Nao informado."
        regra_pagamento    = "Nao ha informacao de pagamento configurada — nao mencione pagamento."

    system_prompt = system_prompt.replace("{payment_text_block}", payment_text_block)
    system_prompt = system_prompt.replace("{regra_pagamento}", regra_pagamento)
    system_prompt = system_prompt.replace("{regra_notes}", regra_notes)
    system_prompt = system_prompt.replace("{regra_phone}", regra_phone)

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(conversation_history[-20:])
    messages.append({"role": "user", "content": new_message})

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=messages,
        temperature=0.2,
        max_tokens=1400,
    )

    raw = response.choices[0].message.content.strip()
    raw = re.sub(r"```json\s*", "", raw)
    raw = re.sub(r"```\s*",     "", raw).strip()

    json_str = extract_json_object(raw)
    if json_str:
        try:
            result = json.loads(json_str)
            if result.get("action") == "create_appointment":
                # Sanitizacao por tipo de negocio
                if not biz["needs_subject"]:
                    result["pet_name"]   = None
                    result["pet_breed"]  = None
                    result["pet_weight"] = None
                if not biz["needs_pickup"]:
                    result["pickup_time"] = None
                if not needs_address:
                    result["pickup_address"] = None
                # Garante message sempre presente
                if not result.get("message"):
                    result["message"] = "✅ Agendamento confirmado! Ate la 😊"
            return result
        except json.JSONDecodeError:
            pass

    # Fallback: se a IA retornou texto puro sem JSON válido
    # trata como reply simples evitando mensagem técnica ao cliente
    if raw and len(raw) < 500 and not raw.startswith('{'):
        return {"action": "reply", "message": raw}
    # Fallback final seguro
    return {"action": "reply", "message": "Desculpe, não entendi. Pode repetir de outra forma? 😊"}