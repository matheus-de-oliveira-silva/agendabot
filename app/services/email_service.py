"""
email_service.py — Serviço de email do BotGen via Resend.

Fix v2:
  - Layout baseado em <table> em vez de flexbox (compatibilidade com Gmail/Outlook)
  - Rebranding: AgendaBot → BotGen
  - Stat boxes usam table layout para clientes de email antigos
  - Inline styles para máxima compatibilidade

Emails enviados:
  1. Boas-vindas pós-compra
  2. Aviso de vencimento (3 dias antes)
  3. Relatório semanal
  4. Plano suspenso
  5. Upgrade confirmado

LGPD:
  - Emails enviados apenas ao titular da conta (billing_email)
  - Nenhum dado de cliente final é incluído
  - Relatório: dados agregados — sem dados individuais identificáveis
"""

import os
import httpx
from datetime import datetime
import pytz

RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
EMAIL_FROM     = os.getenv("EMAIL_FROM", "BotGen <onboarding@resend.dev>")
APP_URL        = os.getenv("APP_URL", "https://web-production-c1b1c.up.railway.app")
BRASILIA       = pytz.timezone("America/Sao_Paulo")

CHECKOUT_LINKS = {
    "basico":  "https://pay.kiwify.com.br/ypIXFRM",
    "pro":     "https://pay.kiwify.com.br/pndpF39",
    "agencia": "https://pay.kiwify.com.br/O0oUFkt",
}

PLAN_NAMES = {
    "basico":  "Básico — R$97,90/mês",
    "pro":     "Pro — R$197,90/mês",
    "agencia": "Agência — R$497,90/mês",
}


# ── Template base (table-based para compatibilidade com todos email clients) ──

def _base_html(content: str) -> str:
    """
    Template HTML compatível com Gmail, Outlook, Apple Mail, Yahoo.
    Usa tabelas em vez de flexbox/grid — padrão da indústria para emails.
    """
    return f"""<!DOCTYPE html>
<html lang="pt-BR" xmlns="http://www.w3.org/1999/xhtml">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta http-equiv="X-UA-Compatible" content="IE=edge">
  <title>BotGen</title>
  <!--[if mso]>
  <noscript><xml><o:OfficeDocumentSettings><o:PixelsPerInch>96</o:PixelsPerInch></o:OfficeDocumentSettings></xml></noscript>
  <![endif]-->
  <style>
    body {{ margin: 0; padding: 0; background-color: #f4f4f8; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif; }}
    a {{ color: #7c3aed; text-decoration: none; }}
    @media only screen and (max-width: 600px) {{
      .email-body {{ width: 100% !important; }}
      .btn-table {{ width: 100% !important; }}
      .stat-cell {{ width: 100% !important; display: block !important; }}
    }}
  </style>
</head>
<body style="margin:0;padding:0;background-color:#f4f4f8;">
  <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:#f4f4f8;">
    <tr>
      <td align="center" style="padding:32px 16px;">
        <table class="email-body" width="600" cellpadding="0" cellspacing="0" border="0" style="max-width:600px;width:100%;background:#ffffff;border-radius:16px;overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,0.08);">

          <!-- Header -->
          <tr>
            <td style="background:linear-gradient(135deg,#1a1a2e 0%,#16213e 100%);padding:36px 32px;text-align:center;">
              <div style="font-size:28px;font-weight:800;color:#ffffff;letter-spacing:-0.5px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;">
                Bot<span style="color:#a78bfa;">Gen</span>
              </div>
              <div style="color:#94a3b8;font-size:13px;margin-top:6px;">Agendamento inteligente pelo WhatsApp</div>
            </td>
          </tr>

          <!-- Conteúdo -->
          <tr>
            <td style="padding:36px 32px;">
              {content}
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="padding:24px 32px;background:#f8fafc;text-align:center;border-top:1px solid #e2e8f0;">
              <p style="font-size:12px;color:#94a3b8;margin:0;line-height:1.6;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;">
                BotGen — Agendamento automático pelo WhatsApp com IA<br>
                <a href="{APP_URL}" style="color:#7c3aed;">botgen.com.br</a> ·
                Você recebe este email por ser cliente BotGen.<br>
                Dúvidas? Responda este email.
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def _btn(text: str, url: str, bg: str = "#7c3aed", color: str = "#ffffff") -> str:
    """Botão compatível com todos os email clients."""
    return f"""<table class="btn-table" cellpadding="0" cellspacing="0" border="0" style="margin:8px auto;">
      <tr>
        <td style="background:{bg};border-radius:10px;text-align:center;">
          <a href="{url}" style="display:inline-block;padding:14px 32px;color:{color};font-weight:700;font-size:15px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;text-decoration:none;">{text}</a>
        </td>
      </tr>
    </table>"""


def _step(num: str, title: str, desc: str, color: str = "#7c3aed") -> str:
    """Linha de onboarding step."""
    return f"""<table cellpadding="0" cellspacing="0" border="0" style="margin-bottom:14px;width:100%;">
      <tr>
        <td width="36" valign="top" style="padding-right:12px;">
          <div style="width:28px;height:28px;background:{color};border-radius:50%;text-align:center;line-height:28px;color:#ffffff;font-weight:800;font-size:13px;">{num}</div>
        </td>
        <td valign="top">
          <div style="font-weight:700;color:#1e293b;font-size:14px;">{title}</div>
          <div style="color:#64748b;font-size:13px;margin-top:2px;">{desc}</div>
        </td>
      </tr>
    </table>"""


def _highlight(text: str) -> str:
    """Caixa de destaque."""
    return f"""<table cellpadding="0" cellspacing="0" border="0" style="width:100%;margin:20px 0;">
      <tr>
        <td style="background:#f8f4ff;border-left:4px solid #7c3aed;padding:16px 20px;border-radius:0 10px 10px 0;">
          <p style="margin:0;color:#4c1d95;font-weight:500;font-size:14px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;">{text}</p>
        </td>
      </tr>
    </table>"""


def _divider() -> str:
    return '<table cellpadding="0" cellspacing="0" border="0" style="width:100%;margin:24px 0;"><tr><td style="height:1px;background:#e2e8f0;"></td></tr></table>'


# ── Envio base ────────────────────────────────────────────────────────────────

async def _send_email(to: str, subject: str, html: str) -> bool:
    """Envia email via API do Resend. Retorna True se enviado com sucesso."""
    if not RESEND_API_KEY:
        print(f"[Email] RESEND_API_KEY não configurada — email não enviado")
        return False

    if not to or "@" not in to:
        print(f"[Email] Endereço inválido — ignorando")
        return False

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {RESEND_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "from":    EMAIL_FROM,
                    "to":      [to],
                    "subject": subject,
                    "html":    html,
                },
            )
            if resp.status_code in (200, 201):
                # LGPD: loga apenas os últimos 8 chars do email
                print(f"[Email] ✅ Enviado | '{subject[:35]}...' | ***{to[-8:]}")
                return True
            else:
                print(f"[Email] ❌ Erro {resp.status_code}: {resp.text[:120]}")
                return False
    except Exception as e:
        print(f"[Email] ❌ Exceção: {e}")
        return False


# ── 1. Email de boas-vindas ───────────────────────────────────────────────────

async def email_boas_vindas(to: str, nome: str, plano: str, dashboard_url: str = "") -> bool:
    """Enviado imediatamente após compra confirmada pela Kiwify."""
    plan_label   = PLAN_NAMES.get(plano, "BotGen")
    nome_display = nome.split()[0] if nome else "olá"

    # Upsell para próximo plano
    upsell_html = ""
    if plano == "basico":
        upsell_html = _divider() + f"""<p style="font-size:13px;color:#64748b;text-align:center;margin:0 0 10px;">Quer mais recursos? Faça upgrade a qualquer momento</p>""" + _btn("Ver Plano Pro — R$197,90/mês", CHECKOUT_LINKS["pro"], "#ffffff", "#6d28d9") .replace("background:#ffffff", "background:transparent").replace("color:#6d28d9", "color:#6d28d9;border:2px solid #7c3aed")
    elif plano == "pro":
        upsell_html = _divider() + f"""<p style="font-size:13px;color:#64748b;text-align:center;margin:0 0 10px;">Tem mais de um negócio?</p>""" + _btn("Ver Plano Agência — R$497,90/mês", CHECKOUT_LINKS["agencia"], "transparent", "#6d28d9")

    dash_btn = ""
    if dashboard_url:
        dash_btn = _divider() + '<p style="font-size:15px;color:#475569;margin:0 0 16px;">Assim que ativado, acesse seu painel aqui:</p>' + _btn("Acessar meu painel →", dashboard_url, "#059669")

    content = f"""
    <h1 style="font-size:22px;font-weight:700;color:#1e293b;margin:0 0 12px;">Bem-vindo ao BotGen, {nome_display}! 🎉</h1>
    <p style="font-size:15px;color:#475569;line-height:1.7;margin:0 0 14px;">Sua assinatura do <strong>{plan_label}</strong> foi confirmada com sucesso. Você acabou de dar um grande passo para automatizar os agendamentos do seu negócio.</p>
    {_highlight("📞 Nossa equipe vai entrar em contato <strong>em até 2 horas</strong> pelo WhatsApp para ativar o seu bot. O processo leva apenas 15 minutos!")}
    <p style="font-size:15px;color:#475569;line-height:1.7;margin:0 0 16px;">Enquanto isso, aqui está o que vai acontecer:</p>
    {_step("1", "Contato pelo WhatsApp", "Nossa equipe vai te ligar para agendar a ativação")}
    {_step("2", "Chamada de 15 minutos", "Conectamos o seu WhatsApp Business e configuramos o bot ao vivo")}
    {_step("3", "Bot ativo!", "Seus clientes já podem agendar pelo WhatsApp automaticamente", "#059669")}
    {dash_btn}
    <p style="font-size:14px;color:#64748b;margin:16px 0 0;">Qualquer dúvida é só responder este email ou nos chamar pelo WhatsApp. Estamos aqui! 😊</p>
    {upsell_html}
    """

    return await _send_email(
        to=to,
        subject="🎉 Bem-vindo ao BotGen! Ativação em até 2h",
        html=_base_html(content),
    )


# ── 2. Email de aviso de vencimento ──────────────────────────────────────────

async def email_aviso_vencimento(to: str, nome: str, plano: str, dias: int = 3) -> bool:
    """Enviado 3 dias antes do vencimento da assinatura."""
    plan_label   = PLAN_NAMES.get(plano, "BotGen")
    nome_display = nome.split()[0] if nome else "olá"
    dias_txt     = f"{dias} {'dia' if dias == 1 else 'dias'}"

    content = f"""
    <h1 style="font-size:22px;font-weight:700;color:#1e293b;margin:0 0 12px;">Ei {nome_display}, sua assinatura vence em {dias_txt} ⏰</h1>
    <p style="font-size:15px;color:#475569;line-height:1.7;margin:0 0 14px;">Só um lembrete: sua assinatura do <strong>{plan_label}</strong> será renovada automaticamente em <strong>{dias_txt}</strong>.</p>
    <table cellpadding="0" cellspacing="0" border="0" style="width:100%;margin:20px 0;">
      <tr><td style="background:#fef3c7;border:1px solid #fbbf24;border-radius:10px;padding:16px 20px;">
        <p style="margin:0;color:#92400e;font-size:14px;">💳 A cobrança é automática pelo método de pagamento cadastrado na Kiwify. Nenhuma ação necessária se quiser continuar.</p>
      </td></tr>
    </table>
    <p style="font-size:14px;color:#475569;line-height:1.7;margin:0 0 14px;">Para cancelar antes da renovação, acesse sua conta na Kiwify. Seu bot continua ativo até o fim do período pago.</p>
    {_divider()}
    <p style="font-size:14px;color:#64748b;margin:0;">Tem alguma dúvida ou problema? Responda este email 😊</p>
    """

    return await _send_email(
        to=to,
        subject=f"⏰ Sua assinatura BotGen renova em {dias_txt}",
        html=_base_html(content),
    )


# ── 3. Email de plano suspenso ────────────────────────────────────────────────

async def email_plano_suspenso(to: str, nome: str, motivo: str = "cancelamento") -> bool:
    """Enviado quando o plano é suspenso."""
    nome_display = nome.split()[0] if nome else "olá"
    motivos = {
        "chargeback":    "uma disputa de pagamento",
        "reembolso":     "um pedido de reembolso",
        "cancelamento":  "o cancelamento da assinatura",
        "inadimplencia": "uma falha no pagamento",
    }
    motivo_texto = motivos.get(motivo, "uma alteração na assinatura")

    content = f"""
    <h1 style="font-size:22px;font-weight:700;color:#1e293b;margin:0 0 12px;">Sua conta foi suspensa, {nome_display}</h1>
    <p style="font-size:15px;color:#475569;line-height:1.7;margin:0 0 14px;">Identificamos {motivo_texto} associado à sua conta BotGen. Por isso, o seu bot foi pausado temporariamente.</p>
    <table cellpadding="0" cellspacing="0" border="0" style="width:100%;margin:20px 0;">
      <tr><td style="background:#fee2e2;border:1px solid #fca5a5;border-radius:10px;padding:16px 20px;">
        <p style="margin:0;color:#991b1b;font-size:14px;">⚠️ Seus dados estão preservados. O bot foi apenas pausado — nenhuma informação foi excluída.</p>
      </td></tr>
    </table>
    <p style="font-size:15px;color:#475569;line-height:1.7;margin:0 0 16px;">Para reativar o BotGen, assine novamente:</p>
    <table cellpadding="0" cellspacing="0" border="0" style="width:100%;">
      <tr><td style="padding-bottom:10px;">{_btn("⭐ Plano Básico — R$97,90/mês", CHECKOUT_LINKS['basico'], "#4c1d95")}</td></tr>
      <tr><td style="padding-bottom:10px;">{_btn("🚀 Plano Pro — R$197,90/mês", CHECKOUT_LINKS['pro'])}</td></tr>
      <tr><td>{_btn("🏢 Plano Agência — R$497,90/mês", CHECKOUT_LINKS['agencia'], "#1e293b")}</td></tr>
    </table>
    {_divider()}
    <p style="font-size:14px;color:#64748b;margin:0;">Se acha que houve um engano, responda este email que a gente verifica imediatamente.</p>
    """

    return await _send_email(
        to=to,
        subject="⚠️ Sua conta BotGen foi suspensa",
        html=_base_html(content),
    )


# ── 4. Relatório semanal ──────────────────────────────────────────────────────

async def email_relatorio_semanal(
    to: str, nome: str, biz_name: str,
    stats: dict, dashboard_url: str,
) -> bool:
    """
    Relatório semanal enviado toda segunda-feira às 8h.
    LGPD: stats são contagens/médias — nunca dados pessoais identificáveis.

    stats esperado:
      total_semana, total_mes, horario_mais_popular,
      servico_mais_popular, novos_clientes, taxa_confirmacao (0.0-1.0)
    """
    nome_display = nome.split()[0] if nome else "olá"
    total        = stats.get("total_semana", 0)
    total_mes    = stats.get("total_mes", 0)
    horario_pop  = stats.get("horario_mais_popular", "—")
    servico_pop  = stats.get("servico_mais_popular", "—")
    novos        = stats.get("novos_clientes", 0)
    taxa         = stats.get("taxa_confirmacao", 1.0)
    taxa_pct     = int(taxa * 100)
    semana_ref   = datetime.now(BRASILIA).strftime("%d/%m/%Y")

    # Stats em tabela (compatível com Outlook)
    stats_table = f"""<table cellpadding="0" cellspacing="0" border="0" style="width:100%;margin:20px 0;">
      <tr>
        <td class="stat-cell" width="33%" style="padding:8px;text-align:center;">
          <table cellpadding="0" cellspacing="0" border="0" style="width:100%;background:#f8f4ff;border-radius:10px;">
            <tr><td style="padding:16px 8px;text-align:center;">
              <div style="font-size:32px;font-weight:800;color:#7c3aed;">{total}</div>
              <div style="font-size:12px;color:#64748b;margin-top:4px;">Agendamentos esta semana</div>
            </td></tr>
          </table>
        </td>
        <td class="stat-cell" width="33%" style="padding:8px;text-align:center;">
          <table cellpadding="0" cellspacing="0" border="0" style="width:100%;background:#f8f4ff;border-radius:10px;">
            <tr><td style="padding:16px 8px;text-align:center;">
              <div style="font-size:32px;font-weight:800;color:#7c3aed;">{total_mes}</div>
              <div style="font-size:12px;color:#64748b;margin-top:4px;">Total no mês</div>
            </td></tr>
          </table>
        </td>
        <td class="stat-cell" width="33%" style="padding:8px;text-align:center;">
          <table cellpadding="0" cellspacing="0" border="0" style="width:100%;background:#f8f4ff;border-radius:10px;">
            <tr><td style="padding:16px 8px;text-align:center;">
              <div style="font-size:32px;font-weight:800;color:#7c3aed;">{novos}</div>
              <div style="font-size:12px;color:#64748b;margin-top:4px;">Clientes novos</div>
            </td></tr>
          </table>
        </td>
      </tr>
    </table>"""

    content = f"""
    <h1 style="font-size:22px;font-weight:700;color:#1e293b;margin:0 0 12px;">Relatório semanal — {biz_name} 📊</h1>
    <p style="font-size:15px;color:#475569;line-height:1.7;margin:0 0 16px;">Olá, {nome_display}! Aqui está o resumo da semana (até {semana_ref}).</p>
    {stats_table}
    <table cellpadding="0" cellspacing="0" border="0" style="width:100%;margin:0 0 10px;">
      <tr><td style="background:#f8f4ff;border-radius:10px;padding:16px;margin-bottom:10px;">
        <div style="font-size:11px;color:#64748b;text-transform:uppercase;letter-spacing:.5px;margin-bottom:4px;">Horário mais agendado</div>
        <div style="font-size:20px;font-weight:700;color:#6d28d9;">🕐 {horario_pop}</div>
      </td></tr>
    </table>
    <table cellpadding="0" cellspacing="0" border="0" style="width:100%;margin:0 0 10px;">
      <tr><td style="background:#f8f4ff;border-radius:10px;padding:16px;">
        <div style="font-size:11px;color:#64748b;text-transform:uppercase;letter-spacing:.5px;margin-bottom:4px;">Serviço mais popular</div>
        <div style="font-size:20px;font-weight:700;color:#6d28d9;">✂️ {servico_pop}</div>
      </td></tr>
    </table>
    <table cellpadding="0" cellspacing="0" border="0" style="width:100%;margin:0 0 24px;">
      <tr><td style="background:#f0fdf4;border-radius:10px;padding:16px;">
        <div style="font-size:11px;color:#64748b;text-transform:uppercase;letter-spacing:.5px;margin-bottom:4px;">Taxa de confirmação</div>
        <div style="font-size:20px;font-weight:700;color:#059669;">✅ {taxa_pct}%</div>
      </td></tr>
    </table>
    {_btn("Ver painel completo →", dashboard_url)}
    {_divider()}
    <p style="font-size:12px;color:#94a3b8;text-align:center;margin:0;">Você recebe este relatório toda segunda-feira.</p>
    """

    return await _send_email(
        to=to,
        subject=f"📊 Relatório semanal — {biz_name} ({total} agendamentos)",
        html=_base_html(content),
    )


# ── 5. Email de upgrade confirmado ────────────────────────────────────────────

async def email_upgrade_confirmado(to: str, nome: str, plano_novo: str) -> bool:
    """Enviado quando o cliente faz upgrade de plano."""
    plan_label   = PLAN_NAMES.get(plano_novo, plano_novo)
    nome_display = nome.split()[0] if nome else "olá"

    novos_recursos = {
        "pro": [
            "Lembretes automáticos para seus clientes no dia anterior",
            "Serviços ilimitados cadastrados",
            "Exportação de agendamentos em CSV",
            "Relatório semanal por email",
        ],
        "agencia": [
            "Tudo do plano Pro",
            "Até 3 negócios diferentes no mesmo plano",
            "Suporte prioritário",
        ],
    }
    recursos = novos_recursos.get(plano_novo, [])
    recursos_html = ""
    if recursos:
        recursos_html = "<p style='font-size:15px;color:#1e293b;font-weight:700;margin:16px 0 10px;'>O que você ganhou:</p>"
        for r in recursos:
            recursos_html += f'<p style="font-size:14px;color:#475569;margin:0 0 8px;padding-left:16px;">✅ {r}</p>'

    content = f"""
    <h1 style="font-size:22px;font-weight:700;color:#1e293b;margin:0 0 12px;">Upgrade confirmado! 🚀</h1>
    <p style="font-size:15px;color:#475569;line-height:1.7;margin:0 0 14px;">Boa notícia, {nome_display}! Seu plano foi atualizado para <strong>{plan_label}</strong>.</p>
    {_highlight("✅ Todos os novos recursos já estão disponíveis agora mesmo.")}
    {recursos_html}
    <p style="font-size:14px;color:#64748b;margin:16px 0 0;">Aproveite! Qualquer dúvida é só chamar 😊</p>
    """

    return await _send_email(
        to=to,
        subject=f"🚀 Upgrade confirmado — Bem-vindo ao {plan_label}!",
        html=_base_html(content),
    )