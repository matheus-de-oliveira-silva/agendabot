"""
ai_service.py — Motor de IA do AgendaBot.

Melhorias v2:
- Tom e personalidade realmente adaptados por tipo de negócio
- Resumo sem linha de pet para negócios que não precisam
- Normalização de horário ("10h", "dez horas" → "10:00")
- Feriados dinâmicos (ano atual + próximo)
- max_tokens aumentado para 1400
- Instrução para resolver serviço ambíguo
- Confirmação de agendamento gerada pela IA (não hardcoded no webhook)
- Contexto de cliente recorrente com personalização real
"""

from openai import OpenAI
from dotenv import load_dotenv
from datetime import datetime, timedelta
from typing import Optional
import pytz, os, json, re

load_dotenv()

client  = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
BRASILIA = pytz.timezone("America/Sao_Paulo")


def agora_brasilia() -> datetime:
    return datetime.now(BRASILIA).replace(tzinfo=None)


# ── Feriados dinâmicos ────────────────────────────────────────────────────────

def _get_feriados() -> dict:
    """
    Retorna feriados nacionais fixos para o ano atual e o próximo.
    Não depende de API externa — cobre os feriados de data fixa.
    Carnaval e Corpus Christi são calculados com base na Páscoa.
    """
    def easter(year: int) -> datetime:
        # Algoritmo de Butcher para calcular a Páscoa
        a = year % 19
        b = year // 100
        c = year % 100
        d = b // 4
        e = b % 4
        f = (b + 8) // 25
        g = (b - f + 1) // 3
        h = (19 * a + b - d - g + 15) % 30
        i = c // 4
        k = c % 4
        l = (32 + 2 * e + 2 * i - h - k) % 7
        m = (a + 11 * h + 22 * l) // 451
        month = (h + l - 7 * m + 114) // 31
        day   = ((h + l - 7 * m + 114) % 31) + 1
        return datetime(year, month, day)

    feriados = {}
    for year in [datetime.now().year, datetime.now().year + 1]:
        pascoa        = easter(year)
        carnaval_seg  = pascoa - timedelta(days=48)
        carnaval_ter  = pascoa - timedelta(days=47)
        sexta_santa   = pascoa - timedelta(days=2)
        corpus_christi = pascoa + timedelta(days=60)

        fixos = [
            f"{year}-01-01",  # Confraternização Universal
            f"{year}-04-21",  # Tiradentes
            f"{year}-05-01",  # Dia do Trabalho
            f"{year}-09-07",  # Independência
            f"{year}-10-12",  # N.Sra. Aparecida
            f"{year}-11-02",  # Finados
            f"{year}-11-15",  # Proclamação da República
            f"{year}-12-25",  # Natal
        ]
        moveis = [
            carnaval_seg.strftime("%Y-%m-%d"),
            carnaval_ter.strftime("%Y-%m-%d"),
            sexta_santa.strftime("%Y-%m-%d"),
            pascoa.strftime("%Y-%m-%d"),
            corpus_christi.strftime("%Y-%m-%d"),
        ]
        nomes = {
            carnaval_seg.strftime("%Y-%m-%d"): "Carnaval (segunda)",
            carnaval_ter.strftime("%Y-%m-%d"): "Carnaval (terça)",
            sexta_santa.strftime("%Y-%m-%d"):  "Sexta-Feira Santa",
            pascoa.strftime("%Y-%m-%d"):        "Páscoa",
            corpus_christi.strftime("%Y-%m-%d"): "Corpus Christi",
            f"{year}-01-01": "Ano Novo",
            f"{year}-04-21": "Tiradentes",
            f"{year}-05-01": "Dia do Trabalho",
            f"{year}-09-07": "Independência do Brasil",
            f"{year}-10-12": "Nossa Sra. Aparecida",
            f"{year}-11-02": "Finados",
            f"{year}-11-15": "Proclamação da República",
            f"{year}-12-25": "Natal",
        }
        for d in fixos + moveis:
            feriados[d] = nomes.get(d, "Feriado")
    return feriados

FERIADOS = _get_feriados()


def _build_feriados_prompt() -> str:
    agora = agora_brasilia()
    # Mostra apenas os próximos 90 dias para não poluir o prompt
    limite = agora + timedelta(days=90)
    proximos = {
        d: nome for d, nome in sorted(FERIADOS.items())
        if agora.strftime("%Y-%m-%d") <= d <= limite.strftime("%Y-%m-%d")
    }
    if not proximos:
        return "Nenhum feriado nos proximos 90 dias."
    return "\n".join(f"  {d}: {nome}" for d, nome in proximos.items())


# ── Helpers de prompt ─────────────────────────────────────────────────────────

def build_services_prompt(services: list) -> str:
    if not services:
        return "Nenhum servico cadastrado no momento."
    lines = []
    for s in services:
        price = f"R$ {s['price']/100:.2f}" if s.get("price") else "Gratis"
        desc  = f" | {s['description']}" if s.get("description") else ""
        lines.append(
            f'  chave="{s["key"]}" | nome="{s["name"]}" | {price} | {s["duration_min"]}min{desc}'
        )
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
            if esc:        esc = False
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
        "personality": (
            "Voce e calorosa, simpatica e visivelmente amante dos animais. "
            "Fale como uma funcionaria do pet shop que conhece cada bichinho pelo nome. "
            "Use expressoes como 'que fofura!', 'que gracinha!', 'que lindinho!'. "
            "Demonstre cuidado genuino com os pets. Emojis de animais sao bem-vindos."
        ),
        "tom_confirmacao": (
            "Na confirmacao, demonstre carinho com o pet. "
            "Ex: 'Que otimo! O [pet] vai ficar lindinho! 🐾'"
        ),
        "needs_subject":   True,
        "subject_fields":  "nome, raca e peso (aproximado)",
        "needs_pickup":    True,
        "resumo_subject":  True,
        "resumo_pickup":   True,
        "campos_obrigatorios": "customer_name, pet_name, pet_breed, pet_weight, service, datetime, pickup_time",
        "saudacao_extra": "Aqui cuidamos do seu pet com muito amor! 🐾",
    },
    "clinica": {
        "emoji": "🏥",
        "personality": (
            "Voce e profissional, empatica e acolhedora. "
            "Fale como recepcionista de clinica veterinaria experiente. "
            "Tom mais formal que petshop mas ainda humano. "
            "Transmita seguranca e competencia."
        ),
        "tom_confirmacao": (
            "Na confirmacao, seja profissional e tranquilizadora. "
            "Ex: 'Perfeito! Sua consulta esta confirmada. Qualquer duvida estamos aqui. 🏥'"
        ),
        "needs_subject":   True,
        "subject_fields":  "nome e especie/raca (peso se relevante para o servico)",
        "needs_pickup":    False,
        "resumo_subject":  True,
        "resumo_pickup":   False,
        "campos_obrigatorios": "customer_name, pet_name, pet_breed, service, datetime",
        "saudacao_extra": "Cuidando da saude do seu pet com dedicacao! 🏥",
    },
    "adocao": {
        "emoji": "❤️",
        "personality": (
            "Voce e calorosa, apaixonada por animais e engajada em adocao responsavel. "
            "Fale como voluntaria que acredita profundamente na causa. "
            "Transmita esperanca e otimismo. Celebre cada passo do processo."
        ),
        "tom_confirmacao": (
            "Na confirmacao, celebre o momento. "
            "Ex: 'Que momento lindo! Voce esta fazendo a diferenca na vida de um animal. ❤️'"
        ),
        "needs_subject":   True,
        "subject_fields":  "nome e especie/raca do animal",
        "needs_pickup":    False,
        "resumo_subject":  True,
        "resumo_pickup":   False,
        "campos_obrigatorios": "customer_name, pet_name, pet_breed, service, datetime",
        "saudacao_extra": "Cada adocao e um ato de amor! ❤️",
    },
    "barbearia": {
        "emoji": "💈",
        "personality": (
            "Voce e descontraida, parceira e com bom humor. "
            "Fale como barbeiro amigo que ja conhece os clientes pelo nome. "
            "Use gírias masculinas naturais: 'mano', 'cara', 'show', 'firmeza'. "
            "Seja direto e objetivo — homem nao quer papo longo. "
            "Sem floreados, sem emojis excessivos."
        ),
        "tom_confirmacao": (
            "Na confirmacao, seja direto e animado. "
            "Ex: 'Show! Ta na agenda. Qualquer coisa e so chamar, parceiro! ✂️'"
        ),
        "needs_subject":   False,
        "subject_fields":  "",
        "needs_pickup":    False,
        "resumo_subject":  False,
        "resumo_pickup":   False,
        "campos_obrigatorios": "customer_name, service, datetime",
        "saudacao_extra": "Seu visual em boas maos! 💈",
    },
    "salao": {
        "emoji": "💅",
        "personality": (
            "Voce e animada, acolhedora e sempre bem-humorada. "
            "Fale como cabeleireira amiga, atualizada nas tendencias. "
            "Use expressoes como 'amei!', 'que otimo!', 'vai ficar lindo(a)!'. "
            "Emojis femininos e coloridos sao bem-vindos. Tom alegre e afetuoso."
        ),
        "tom_confirmacao": (
            "Na confirmacao, seja entusiasmada. "
            "Ex: 'Perfeito! Vai ficar arrasando! Ate la! 💅✨'"
        ),
        "needs_subject":   False,
        "subject_fields":  "",
        "needs_pickup":    False,
        "resumo_subject":  False,
        "resumo_pickup":   False,
        "campos_obrigatorios": "customer_name, service, datetime",
        "saudacao_extra": "Beleza e o que nao vai faltar aqui! 💅",
    },
    "estetica": {
        "emoji": "✨",
        "personality": (
            "Voce e elegante, atenciosa e sofisticada. "
            "Fale como especialista em bem-estar que valoriza cada cliente. "
            "Tom refinado mas acessivel. Transmita exclusividade e cuidado. "
            "Evite gírias. Prefira 'encantadora', 'maravilhosa', 'sublime'."
        ),
        "tom_confirmacao": (
            "Na confirmacao, seja elegante. "
            "Ex: 'Maravilhoso! Seu horario esta confirmado. Sera um prazer recebe-la. ✨'"
        ),
        "needs_subject":   False,
        "subject_fields":  "",
        "needs_pickup":    False,
        "resumo_subject":  False,
        "resumo_pickup":   False,
        "campos_obrigatorios": "customer_name, service, datetime",
        "saudacao_extra": "Voce merece o melhor cuidado! ✨",
    },
    "outro": {
        "emoji": "📅",
        "personality": (
            "Voce e simpatica, prestativa e eficiente. "
            "Fale como boa recepcionista que conhece bem o negocio. "
            "Tom cordial e profissional. Adapte-se ao tipo de cliente."
        ),
        "tom_confirmacao": (
            "Na confirmacao, seja cordial e clara. "
            "Ex: 'Otimo! Agendamento confirmado. Ate la! 😊'"
        ),
        "needs_subject":   False,
        "subject_fields":  "",
        "needs_pickup":    False,
        "resumo_subject":  False,
        "resumo_pickup":   False,
        "campos_obrigatorios": "customer_name, service, datetime",
        "saudacao_extra": "Estamos aqui para ajudar! 😊",
    },
}

def get_biz(business_type: str) -> dict:
    return BUSINESS_CONFIG.get(business_type, BUSINESS_CONFIG["outro"])


# ── Builders de seção do prompt ───────────────────────────────────────────────

def build_resumo_template(biz: dict, subject: str, needs_address: bool, address_label: str) -> str:
    """Monta o template de resumo adaptado ao tipo de negócio."""
    lines = []
    if biz["resumo_subject"]:
        lines.append(f'{biz["emoji"]} {subject}: [nome] ([detalhe])')
    lines.append("👤 Cliente: [nome real do cliente]")
    lines.append("✂️ Servico: [servico] — [preco]")
    lines.append("📅 [data por extenso] as [hora]")
    if biz["resumo_pickup"]:
        lines.append("🏠 Busca: [horario de busca]")
    if needs_address:
        lines.append(f"📍 {address_label}: [endereco completo]")
    lines.append("\nTa certinho assim? 😊")
    return "\n".join(lines)


def build_create_example(biz: dict, svc_key: str, needs_address: bool) -> dict:
    """Monta o exemplo de JSON create_appointment."""
    base = {
        "action":        "create_appointment",
        "customer_name": "Joao Silva",
        "service":       svc_key,
        "datetime":      "YYYY-MM-DDTHH:MM:00",
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
    base["pickup_address"] = "Rua das Flores, 123 — Centro" if needs_address else None
    return base


def build_cancel_example() -> dict:
    return {"action": "cancel_appointment", "appointment_index": 1}


def build_availability_example(svc_key: str) -> dict:
    return {"action": "check_availability", "date": "YYYY-MM-DD", "service": svc_key}


def build_availability_specific_example(svc_key: str) -> dict:
    return {"action": "check_availability", "date": "YYYY-MM-DD", "service": svc_key, "requested_time": "HH:MM"}


# ── Função principal ──────────────────────────────────────────────────────────

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
    subject        = cfg.get("subject_label") or "Cliente"
    subject_plural = cfg.get("subject_label_plural") or "Clientes"
    needs_address  = bool(cfg.get("needs_address", False))
    address_label  = cfg.get("address_label") or "Endereço de busca"

    biz     = get_biz(biz_type)
    svc_key = (services[0].get("key", "servico") if services else "servico")

    # Exemplos de JSON formatados
    ex_avail    = json.dumps(build_availability_example(svc_key),          ensure_ascii=False)
    ex_avail_sp = json.dumps(build_availability_specific_example(svc_key), ensure_ascii=False)
    ex_create   = json.dumps(build_create_example(biz, svc_key, needs_address), ensure_ascii=False, indent=2)
    ex_cancel   = json.dumps(build_cancel_example(), ensure_ascii=False)
    resumo_tmpl = build_resumo_template(biz, subject, needs_address, address_label)

    hours_text    = build_hours_prompt(cfg)
    services_text = build_services_prompt(services or [])
    feriados_text = _build_feriados_prompt()

    # ── Contexto do cliente ───────────────────────────────────────────────────
    ctx_lines, nome_conhecido = [], False
    cliente_recorrente = False

    if customer_context:
        nome = (customer_context.get("name") or "").strip()
        if nome and len(nome) >= 2:
            nome_conhecido = True
            ctx_lines.append(f"NOME: {nome}")

        pets = customer_context.get("pets", [])
        if pets and biz["needs_subject"]:
            ctx_lines.append(f"{subject_plural.upper()} JA CADASTRADOS:")
            for p in pets:
                s = f"  - {p['name']}"
                if p.get("breed"):  s += f" ({p['breed']}"
                if p.get("weight"): s += f", {p['weight']}kg"
                if p.get("breed"):  s += ")"
                ctx_lines.append(s)

        n = customer_context.get("total_appointments", 0)
        if n > 0:
            cliente_recorrente = True
            ctx_lines.append(f"RECORRENTE: sim ({n} agendamento(s) anteriores)")
        else:
            ctx_lines.append("RECORRENTE: nao — primeira vez")

    ctx_block = "\n".join(ctx_lines) if ctx_lines else "Cliente novo sem dados."

    # ── Blocos condicionais do prompt ─────────────────────────────────────────

    # Nome
    if nome_conhecido:
        nome_real   = customer_context.get("name", "")
        regra_nome  = f"NOME JA CONHECIDO: '{nome_real}'. Use-o naturalmente. NAO pergunte o nome de novo."
        saudacao    = f"Oi {nome_real}! " + ("Que saudade! 😊 " if cliente_recorrente else "")
    else:
        regra_nome  = (
            "NOME DESCONHECIDO: A PRIMEIRA coisa que voce deve fazer e perguntar o nome. "
            "Sem excecoes. Mesmo que o cliente mande servico+data+hora tudo junto, "
            "peca o nome primeiro (ou dispare check_availability em paralelo enquanto pede o nome). "
            "NUNCA coloque '[Nome do Cliente]' ou '[nome]' no resumo — use sempre o nome real coletado."
        )
        saudacao = f"Oi! Bem-vindo(a) ao {biz_name}! 😊"

    # Recorrente
    if cliente_recorrente and biz["needs_subject"] and customer_context.get("pets"):
        pets_str = ", ".join(p["name"] for p in customer_context["pets"])
        regra_recorrente = (
            f"CLIENTE RECORRENTE: demonstre que reconhece. Ex: 'Que saudade! Vai trazer o {pets_str} de novo? 😊'. "
            f"Se o cliente confirmar o mesmo pet, nao precisa perguntar raca/peso de novo — ja temos no cadastro."
        )
    elif cliente_recorrente:
        regra_recorrente = "CLIENTE RECORRENTE: demonstre que reconhece. Ex: 'Que saudade! 😊'"
    else:
        regra_recorrente = "CLIENTE NOVO: seja acolhedor(a) e prestativo(a)."

    # Subject (pet / animal / nada)
    if biz["needs_subject"]:
        regra_subject = (
            f"COLETA DE DADOS DO {subject.upper()}: apos confirmar servico e horario, "
            f"colete {biz['subject_fields']} do {subject.lower()}. "
            f"Se o cliente ja trouxe essa informacao antes (ver contexto), nao pergunte de novo."
        )
    else:
        regra_subject = (
            f"IMPORTANTE: NAO pergunte sobre pet, animal, raca, especie ou peso. "
            f"Este negocio NAO trabalha com animais. "
            f"Campos pet_name, pet_breed e pet_weight devem ser SEMPRE null no JSON. "
            f"O cliente e o proprio sujeito do agendamento."
        )

    # Pickup
    if biz["needs_pickup"]:
        regra_pickup = (
            f"HORARIO DE BUSCA: apos confirmar o servico e horario do agendamento, "
            f"pergunte o horario em que o cliente quer que busquem o {subject.lower()}. "
            f"Ex: 'A que horas posso mandar buscar o {subject.lower()}? 🏠'"
        )
    else:
        regra_pickup = "NAO pergunte horario de busca. pickup_time = null sempre."

    # Endereço
    if needs_address:
        regra_address = (
            f"COLETA DE ENDERECO (OBRIGATORIA): apos confirmar horario "
            f"{'e horario de busca' if biz['needs_pickup'] else ''}, "
            f"pergunte o endereco completo. "
            f"Pergunta sugerida: 'Qual o {address_label.lower()}? 📍 (rua, numero e bairro)'. "
            f"Inclua no JSON: \"pickup_address\": \"[endereco informado]\". "
            f"Mostre no resumo: 📍 {address_label}: [endereco]. "
            f"NUNCA crie agendamento sem endereco quando needs_address=true."
        )
    else:
        regra_address = "NAO pergunte endereco. pickup_address = null sempre."

    # Campos obrigatórios
    campos = biz["campos_obrigatorios"]
    if needs_address:
        campos += ", pickup_address"

    # Serviço ambíguo
    if services and len(services) > 1:
        nomes_svc = ", ".join(f'"{s["name"]}"' for s in services[:6])
        regra_servico_ambiguo = (
            f"SERVICO AMBIGUO: se o cliente descrever um servico de forma vaga e houver multiplas opcoes, "
            f"apresente as opcoes e peca para ele escolher. "
            f"Ex: cliente fala 'quero cortar o cabelo' e ha '{nomes_svc}' — pergunte qual. "
            f"Use EXATAMENTE a chave (key) do servico escolhido no JSON."
        )
    else:
        regra_servico_ambiguo = ""

    # ── Bloco de interpretação de horário ─────────────────────────────────────
    regra_horario_texto = """
INTERPRETACAO DE HORARIO (CRITICA):
- Normalize SEMPRE para HH:MM antes de usar no JSON.
- Exemplos de normalizacao:
  "10h" → "10:00" | "10 horas" → "10:00" | "dez horas" → "10:00"
  "10:30" → "10:30" | "as 14h" → "14:00" | "duas da tarde" → "14:00"
  "meio dia" → "12:00" | "meia noite" → "00:00"
  "9h30" → "09:30" | "9 e meia" → "09:30"
- Se o cliente pedir horario ESPECIFICO: use requested_time com o valor normalizado.
- Se o cliente NAO pedir horario: liste os disponiveis (check_availability sem requested_time).
"""

    # ── Montagem do system prompt ─────────────────────────────────────────────
    system_prompt = f"""Voce e {attendant}, atendente virtual de {biz_name}.

=== SUA PERSONALIDADE ===
{biz["personality"]}
{biz["tom_confirmacao"]}
Saudacao inicial padrao: "{saudacao}"
Frase de apresentacao: "{biz['saudacao_extra']}"

=== CONTEXTO ATUAL ===
Data: {data_hoje} ({dia_semana}) | Hora atual: {hora_agora} | Amanha: {data_amanha}

DADOS DO CLIENTE:
{ctx_block}

=== REGRAS ABSOLUTAS — NUNCA QUEBRE ===

[1] NOME DO CLIENTE:
{regra_nome}

[2] RECORRENCIA:
{regra_recorrente}

[3] HORARIO ESPECIFICO vs LISTAGEM:
- Cliente pediu horario ESPECIFICO (ex: "as 10h", "quero 14:00", "pode ser as 9?")?
  → Chame check_availability com requested_time (normalizado para HH:MM)
  → Se disponivel: confirme e siga para proximo passo
  → Se ocupado: informe e oferta os 3 horarios mais proximos
  → NUNCA liste todos os horarios quando o cliente ja pediu um especifico
- Cliente NAO pediu horario especifico?
  → Chame check_availability SEM requested_time e mostre os disponiveis

[4] NAO REPITA PERGUNTAS:
- Se um dado ja foi informado, use-o. NAO pergunte de novo.
- Se falta apenas 1 dado: pergunte SO esse dado em frase curta e direta.
- Se ja tem tudo: va direto para o resumo de confirmacao.

[5] TIPO DE NEGOCIO — DADOS ESPECIFICOS:
{regra_subject}
{regra_pickup}

[6] ENDERECO:
{regra_address}

[7] SERVICO:
{regra_servico_ambiguo if regra_servico_ambiguo else "Use EXATAMENTE a chave (key) do servico no JSON."}

[8] CAMPOS OBRIGATORIOS para create_appointment:
{campos}
NAO crie agendamento sem todos esses dados.

[9] RESUMO ANTES DE CONFIRMAR:
SEMPRE mostre o resumo completo e aguarde confirmacao do cliente ANTES de enviar create_appointment.
Modelo do resumo (adapte ao tipo de negocio):
{resumo_tmpl}

[10] ESCOPO:
Fale SOMENTE sobre servicos de {biz_name}.
Se o cliente falar de outro assunto, responda educadamente que voce so faz agendamentos aqui.

{regra_horario_texto}

=== FUNCIONAMENTO ===
{hours_text}

=== FERIADOS PROXIMOS ===
{feriados_text}
Nao agende em feriados. Se o cliente pedir, informe o feriado e sugira outra data.

=== SERVICOS DISPONIVEIS (use EXATAMENTE as chaves) ===
{services_text}

=== TOM DE CONVERSA ===
- Natural, como WhatsApp real — nunca robotico
- Use o nome do cliente sempre que souber: "Oi {'{nome}'}!", "Perfeito, {'{nome}'}!"
- Emojis naturais (2-3 por mensagem, nao exagere)
- Quando verificar agenda: "Um segundinho! 🗓️"
- Seja direta: se falta 1 dado, pergunte so esse dado
- Linguagem adaptada ao tipo de negocio (ver personalidade acima)

=== FORMATO DE RESPOSTA — SEMPRE JSON PURO ===

Verificar disponibilidade (sem horario especifico):
{ex_avail}

Verificar horario especifico (cliente pediu "as 10h" etc):
{ex_avail_sp}

Criar agendamento (somente apos resumo confirmado pelo cliente):
{ex_create}

Listar agendamentos:
{{"action":"list_appointments"}}

Cancelar agendamento:
{ex_cancel}

Resposta de texto normal:
{{"action":"reply","message":"sua mensagem aqui"}}

REGRAS DO JSON:
- SEMPRE JSON puro — sem markdown, sem texto fora do JSON
- "service": use SOMENTE as chaves exatas listadas nos servicos
- "datetime": formato exato "YYYY-MM-DDTHH:MM:00"
- "requested_time": sempre normalizado "HH:MM"
- Campos null quando nao aplicavel (pet_name, pet_breed, pet_weight, pickup_time, pickup_address)
- NUNCA invente campos que nao existem no modelo acima
"""

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(conversation_history[-20:])
    messages.append({"role": "user", "content": new_message})

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=messages,
        temperature=0.25,   # Levemente mais determinístico para JSONs
        max_tokens=1400,    # Aumentado para suportar resumos longos
    )

    raw = response.choices[0].message.content.strip()

    # Remove markdown se a IA "escapar" do formato
    raw = re.sub(r"```json\s*", "", raw)
    raw = re.sub(r"```\s*",     "", raw).strip()

    json_str = extract_json_object(raw)
    if json_str:
        try:
            result = json.loads(json_str)
            # Sanitização: garante que campos nulos de outros tipos não vazem
            if result.get("action") == "create_appointment":
                if not biz["needs_subject"]:
                    result["pet_name"]   = None
                    result["pet_breed"]  = None
                    result["pet_weight"] = None
                if not biz["needs_pickup"]:
                    result["pickup_time"] = None
                if not needs_address:
                    result["pickup_address"] = None
            return result
        except json.JSONDecodeError:
            pass

    # Fallback: retorna como reply
    return {"action": "reply", "message": raw}