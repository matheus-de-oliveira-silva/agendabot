"""
email_service.py — Serviço de email do AgendaBot via Resend.

Emails enviados:
  1. Boas-vindas pós-compra (compra_aprovada)
  2. Aviso de vencimento (3 dias antes — reduz churn)
  3. Relatório semanal para o dono do negócio
  4. Aviso de plano suspenso (após cancelamento/chargeback)

LGPD:
  - Emails enviados apenas para o titular da conta (billing_email)
  - Nenhum dado de cliente final é incluído nos emails
  - Conteúdo do relatório é agregado — sem dados individuais identificáveis

Configuração:
  RESEND_API_KEY=re_xxxxxxxxxxxx  (variável de ambiente no Railway)
  EMAIL_FROM=onboarding@resend.dev  (padrão Resend até ter domínio próprio)
"""

import os
import httpx
from datetime import datetime
import pytz

RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
EMAIL_FROM     = os.getenv("EMAIL_FROM", "AgendaBot <onboarding@resend.dev>")
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


# ── Estilos base ──────────────────────────────────────────────────────────────

def _base_html(content: str, preview: str = "") -> str:
    """Template HTML base responsivo com identidade visual do AgendaBot."""
    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>AgendaBot</title>
  {'<meta name="x-apple-disable-message-reformatting">' if preview else ''}
  <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{ background: #f4f4f8; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif; }}
    .wrapper {{ max-width: 600px; margin: 0 auto; padding: 32px 16px; }}
    .card {{ background: #ffffff; border-radius: 16px; overflow: hidden; box-shadow: 0 4px 20px rgba(0,0,0,0.08); }}
    .header {{ background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%); padding: 36px 32px; text-align: center; }}
    .logo {{ font-size: 28px; font-weight: 800; color: #ffffff; letter-spacing: -0.5px; }}
    .logo span {{ color: #a78bfa; }}
    .tagline {{ color: #94a3b8; font-size: 13px; margin-top: 6px; }}
    .body {{ padding: 36px 32px; }}
    h1 {{ font-size: 22px; font-weight: 700; color: #1e293b; margin-bottom: 12px; }}
    p {{ font-size: 15px; color: #475569; line-height: 1.7; margin-bottom: 14px; }}
    .highlight {{ background: #f8f4ff; border-left: 4px solid #7c3aed; padding: 16px 20px; border-radius: 0 10px 10px 0; margin: 20px 0; }}
    .highlight p {{ margin: 0; color: #4c1d95; font-weight: 500; }}
    .btn {{ display: inline-block; background: #7c3aed; color: #ffffff !important; text-decoration: none; padding: 14px 32px; border-radius: 10px; font-weight: 700; font-size: 15px; margin: 8px 0; }}
    .btn-outline {{ background: transparent; color: #7c3aed !important; border: 2px solid #7c3aed; }}
    .btn-green {{ background: #059669; }}
    .plan-card {{ background: #f8f4ff; border: 1px solid #e9d5ff; border-radius: 12px; padding: 20px; margin: 12px 0; }}
    .plan-name {{ font-weight: 700; color: #6d28d9; font-size: 16px; }}
    .plan-price {{ font-size: 24px; font-weight: 800; color: #1e293b; }}
    .plan-features {{ margin-top: 10px; }}
    .plan-features li {{ font-size: 13px; color: #475569; padding: 3px 0; list-style: none; }}
    .plan-features li:before {{ content: "✓ "; color: #059669; font-weight: 700; }}
    .divider {{ height: 1px; background: #e2e8f0; margin: 24px 0; }}
    .footer {{ padding: 24px 32px; background: #f8fafc; text-align: center; }}
    .footer p {{ font-size: 12px; color: #94a3b8; margin: 0; line-height: 1.6; }}
    .footer a {{ color: #7c3aed; text-decoration: none; }}
    .stat-row {{ display: flex; gap: 12px; margin: 20px 0; }}
    .stat-box {{ flex: 1; background: #f8f4ff; border-radius: 10px; padding: 16px; text-align: center; }}
    .stat-num {{ font-size: 28px; font-weight: 800; color: #7c3aed; }}
    .stat-label {{ font-size: 12px; color: #64748b; margin-top: 4px; }}
    .alert-box {{ background: #fef3c7; border: 1px solid #fbbf24; border-radius: 10px; padding: 16px 20px; margin: 20px 0; }}
    .alert-box p {{ color: #92400e; margin: 0; }}
    .danger-box {{ background: #fee2e2; border: 1px solid #fca5a5; border-radius: 10px; padding: 16px 20px; margin: 20px 0; }}
    .danger-box p {{ color: #991b1b; margin: 0; }}
    @media (max-width: 480px) {{
      .body {{ padding: 24px 20px; }}
      .stat-row {{ flex-direction: column; }}
    }}
  </style>
</head>
<body>
  <div class="wrapper">
    <div class="card">
      <div class="header">
        <div class="logo">Agenda<span>Bot</span></div>
        <div class="tagline">Agendamento inteligente pelo WhatsApp</div>
      </div>
      <div class="body">
        {content}
      </div>
      <div class="footer">
        <p>
          AgendaBot — Agendamento automático pelo WhatsApp com IA<br>
          <a href="{APP_URL}">agendabot.com.br</a> · 
          Você está recebendo este email por ser cliente AgendaBot.<br>
          Em caso de dúvidas, responda este email.
        </p>
      </div>
    </div>
  </div>
</body>
</html>"""


# ── Envio base ────────────────────────────────────────────────────────────────

async def _send_email(to: str, subject: str, html: str) -> bool:
    """Envia email via API do Resend. Retorna True se enviado com sucesso."""
    if not RESEND_API_KEY:
        print(f"[Email] RESEND_API_KEY não configurada — email não enviado para {to[:4]}***")
        return False

    if not to or "@" not in to:
        print(f"[Email] Endereço inválido — ignorando")
        return False

    async with httpx.AsyncClient() as client:
        try:
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
                timeout=15,
            )
            if resp.status_code in (200, 201):
                print(f"[Email] ✅ Enviado | assunto='{subject[:40]}' | para=***{to[-10:]}")
                return True
            else:
                print(f"[Email] ❌ Erro {resp.status_code}: {resp.text[:100]}")
                return False
        except Exception as e:
            print(f"[Email] ❌ Exceção: {e}")
            return False


# ── 1. Email de boas-vindas ───────────────────────────────────────────────────

async def email_boas_vindas(to: str, nome: str, plano: str, dashboard_url: str = "") -> bool:
    """
    Enviado imediatamente após compra confirmada pela Kiwify.
    Tom: animado, humano, claro sobre os próximos passos.
    LGPD: só dados do próprio comprador.
    """
    plan_label = PLAN_NAMES.get(plano, "AgendaBot")
    upgrade_html = ""

    if plano == "basico":
        upgrade_html = f"""
        <div class="divider"></div>
        <p style="font-size:13px;color:#64748b;text-align:center;">
          Quer mais recursos? Faça upgrade a qualquer momento 👇
        </p>
        <div style="text-align:center;margin-top:8px;">
          <a href="{CHECKOUT_LINKS['pro']}" class="btn btn-outline" style="font-size:13px;padding:10px 20px;">
            Ver Plano Pro — R$197,90/mês
          </a>
        </div>
        """
    elif plano == "pro":
        upgrade_html = f"""
        <div class="divider"></div>
        <p style="font-size:13px;color:#64748b;text-align:center;">
          Tem mais de um negócio? Conheça o Plano Agência 👇
        </p>
        <div style="text-align:center;margin-top:8px;">
          <a href="{CHECKOUT_LINKS['agencia']}" class="btn btn-outline" style="font-size:13px;padding:10px 20px;">
            Ver Plano Agência — R$497,90/mês
          </a>
        </div>
        """

    nome_display = nome.split()[0] if nome else "olá"

    content = f"""
    <h1>Bem-vindo ao AgendaBot, {nome_display}! 🎉</h1>
    <p>Sua assinatura do <strong>{plan_label}</strong> foi confirmada com sucesso. Você acabou de dar um passo enorme para automatizar os agendamentos do seu negócio.</p>

    <div class="highlight">
      <p>📞 Nossa equipe vai entrar em contato <strong>em até 2 horas</strong> pelo WhatsApp para ativar o seu bot. O processo leva apenas 15 minutos!</p>
    </div>

    <p>Enquanto isso, aqui está o que vai acontecer:</p>

    <div style="margin: 20px 0;">
      <div style="display:flex;align-items:flex-start;gap:12px;margin-bottom:14px;">
        <div style="width:28px;height:28px;background:#7c3aed;border-radius:50%;display:flex;align-items:center;justify-content:center;color:white;font-weight:700;font-size:13px;flex-shrink:0;">1</div>
        <div><strong style="color:#1e293b;">Contato pelo WhatsApp</strong><br><span style="color:#64748b;font-size:14px;">Nossa equipe vai te ligar para agendar a ativação</span></div>
      </div>
      <div style="display:flex;align-items:flex-start;gap:12px;margin-bottom:14px;">
        <div style="width:28px;height:28px;background:#7c3aed;border-radius:50%;display:flex;align-items:center;justify-content:center;color:white;font-weight:700;font-size:13px;flex-shrink:0;">2</div>
        <div><strong style="color:#1e293b;">Chamada de 15 minutos</strong><br><span style="color:#64748b;font-size:14px;">Conectamos o seu WhatsApp Business e configuramos tudo</span></div>
      </div>
      <div style="display:flex;align-items:flex-start;gap:12px;">
        <div style="width:28px;height:28px;background:#059669;border-radius:50%;display:flex;align-items:center;justify-content:center;color:white;font-weight:700;font-size:13px;flex-shrink:0;">✓</div>
        <div><strong style="color:#1e293b;">Bot ativo!</strong><br><span style="color:#64748b;font-size:14px;">Seus clientes já podem agendar pelo WhatsApp automaticamente</span></div>
      </div>
    </div>

    {f'<div class="divider"></div><p>Assim que ativado, acesse seu painel de agendamentos aqui:</p><div style="text-align:center;margin:20px 0;"><a href="{dashboard_url}" class="btn btn-green">Acessar meu painel →</a></div>' if dashboard_url else ''}

    <p>Qualquer dúvida é só responder este email ou nos chamar pelo WhatsApp. Estamos aqui! 😊</p>
    {upgrade_html}
    """

    return await _send_email(
        to=to,
        subject=f"🎉 Bem-vindo ao AgendaBot! Ativação em até 2h",
        html=_base_html(content),
    )


# ── 2. Email de aviso de vencimento ──────────────────────────────────────────

async def email_aviso_vencimento(to: str, nome: str, plano: str, dias: int = 3) -> bool:
    """
    Enviado 3 dias antes do vencimento da assinatura.
    Objetivo: reduzir churn lembrando o cliente antes de cancelar.
    LGPD: apenas dados do titular da conta.
    """
    plan_label   = PLAN_NAMES.get(plano, "AgendaBot")
    nome_display = nome.split()[0] if nome else "olá"

    content = f"""
    <h1>Ei {nome_display}, sua assinatura vence em {dias} {'dia' if dias == 1 else 'dias'} ⏰</h1>
    <p>Só um lembrete rápido: sua assinatura do <strong>{plan_label}</strong> será renovada automaticamente em <strong>{dias} {'dia' if dias == 1 else 'dias'}</strong>.</p>

    <div class="alert-box">
      <p>💳 A cobrança é automática pelo cartão ou método de pagamento cadastrado na Kiwify. Nenhuma ação necessária se quiser continuar.</p>
    </div>

    <p>Se quiser cancelar antes da renovação, acesse sua conta na Kiwify e cancele por lá. Seu bot continua ativo até o fim do período pago.</p>

    <div class="divider"></div>
    <p style="font-size:14px;color:#64748b;">Tem alguma dúvida ou problema? Responda este email que a gente resolve rapidinho 😊</p>
    """

    return await _send_email(
        to=to,
        subject=f"⏰ Sua assinatura AgendaBot renova em {dias} {'dia' if dias == 1 else 'dias'}",
        html=_base_html(content),
    )


# ── 3. Email de plano suspenso ────────────────────────────────────────────────

async def email_plano_suspenso(to: str, nome: str, motivo: str = "cancelamento") -> bool:
    """
    Enviado quando o plano é suspenso (chargeback, cancelamento, etc).
    Tom: neutro, sem julgamento, abrindo porta para retorno.
    LGPD: apenas dados do titular.
    """
    nome_display = nome.split()[0] if nome else "olá"

    motivos = {
        "chargeback":    "uma disputa de pagamento",
        "reembolso":     "um pedido de reembolso",
        "cancelamento":  "o cancelamento da assinatura",
        "inadimplencia": "uma falha no pagamento",
    }
    motivo_texto = motivos.get(motivo, "uma alteração na assinatura")

    content = f"""
    <h1>Sua conta foi suspensa, {nome_display}</h1>
    <p>Identificamos {motivo_texto} associado à sua conta AgendaBot. Por isso, o seu bot foi pausado temporariamente.</p>

    <div class="danger-box">
      <p>⚠️ Seus dados estão preservados. O bot foi apenas pausado — nenhuma informação foi excluída.</p>
    </div>

    <p>Para reativar o AgendaBot, assine novamente por um dos planos abaixo:</p>

    <div style="text-align:center;margin:24px 0;display:flex;flex-direction:column;gap:10px;">
      <a href="{CHECKOUT_LINKS['basico']}" class="btn" style="background:#6d28d9;">Plano Básico — R$97,90/mês</a>
      <a href="{CHECKOUT_LINKS['pro']}" class="btn">Plano Pro — R$197,90/mês</a>
      <a href="{CHECKOUT_LINKS['agencia']}" class="btn btn-outline">Plano Agência — R$497,90/mês</a>
    </div>

    <p style="font-size:14px;color:#64748b;">Se acha que houve um engano, responda este email que a gente verifica imediatamente.</p>
    """

    return await _send_email(
        to=to,
        subject="⚠️ Sua conta AgendaBot foi suspensa",
        html=_base_html(content),
    )


# ── 4. Relatório semanal ──────────────────────────────────────────────────────

async def email_relatorio_semanal(
    to: str,
    nome: str,
    biz_name: str,
    stats: dict,
    dashboard_url: str,
) -> bool:
    """
    Relatório semanal enviado toda segunda-feira às 8h.
    Dados agregados — sem informações individuais dos clientes finais.
    LGPD: stats são contagens/médias, nunca dados pessoais identificáveis.

    stats esperado:
    {
        "total_semana": int,
        "total_mes": int,
        "horario_mais_popular": str,  # "14:00"
        "servico_mais_popular": str,  # "Corte + Barba"
        "novos_clientes": int,
        "taxa_confirmacao": float,    # 0.0 - 1.0
    }
    """
    nome_display = nome.split()[0] if nome else "olá"
    total        = stats.get("total_semana", 0)
    total_mes    = stats.get("total_mes", 0)
    horario_pop  = stats.get("horario_mais_popular", "—")
    servico_pop  = stats.get("servico_mais_popular", "—")
    novos        = stats.get("novos_clientes", 0)
    taxa         = stats.get("taxa_confirmacao", 1.0)
    taxa_pct     = int(taxa * 100)

    agora      = datetime.now(BRASILIA)
    semana_ref = agora.strftime("%d/%m/%Y")

    content = f"""
    <h1>Relatório semanal — {biz_name} 📊</h1>
    <p>Olá, {nome_display}! Aqui está um resumo do que aconteceu no seu negócio esta semana (até {semana_ref}).</p>

    <div class="stat-row">
      <div class="stat-box">
        <div class="stat-num">{total}</div>
        <div class="stat-label">Agendamentos esta semana</div>
      </div>
      <div class="stat-box">
        <div class="stat-num">{total_mes}</div>
        <div class="stat-label">Total no mês</div>
      </div>
      <div class="stat-box">
        <div class="stat-num">{novos}</div>
        <div class="stat-label">Clientes novos</div>
      </div>
    </div>

    <div style="margin: 20px 0;">
      <div style="background:#f8f4ff;border-radius:10px;padding:16px;margin-bottom:10px;">
        <div style="font-size:12px;color:#64748b;text-transform:uppercase;letter-spacing:.5px;margin-bottom:4px;">Horário mais agendado</div>
        <div style="font-size:20px;font-weight:700;color:#6d28d9;">🕐 {horario_pop}</div>
      </div>
      <div style="background:#f8f4ff;border-radius:10px;padding:16px;margin-bottom:10px;">
        <div style="font-size:12px;color:#64748b;text-transform:uppercase;letter-spacing:.5px;margin-bottom:4px;">Serviço mais popular</div>
        <div style="font-size:20px;font-weight:700;color:#6d28d9;">✂️ {servico_pop}</div>
      </div>
      <div style="background:#f8f4ff;border-radius:10px;padding:16px;">
        <div style="font-size:12px;color:#64748b;text-transform:uppercase;letter-spacing:.5px;margin-bottom:4px;">Taxa de confirmação</div>
        <div style="font-size:20px;font-weight:700;color:#059669;">✅ {taxa_pct}%</div>
      </div>
    </div>

    <div style="text-align:center;margin:24px 0;">
      <a href="{dashboard_url}" class="btn">Ver painel completo →</a>
    </div>

    <p style="font-size:13px;color:#94a3b8;text-align:center;">
      Você recebe este relatório toda segunda-feira. Para desativar, acesse seu painel.
    </p>
    """

    return await _send_email(
        to=to,
        subject=f"📊 Relatório semanal — {biz_name} ({total} agendamentos)",
        html=_base_html(content),
    )


# ── 5. Email de upgrade bem-sucedido ─────────────────────────────────────────

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
    recursos_html = "".join(f"<li>{r}</li>" for r in recursos)

    content = f"""
    <h1>Upgrade confirmado! 🚀</h1>
    <p>Boa notícia, {nome_display}! Seu plano foi atualizado para <strong>{plan_label}</strong>.</p>

    <div class="highlight">
      <p>✅ Todos os novos recursos já estão disponíveis agora mesmo.</p>
    </div>

    {'<p><strong>O que você ganhou:</strong></p><ul class="plan-features" style="margin:10px 0 20px 0;">' + recursos_html + '</ul>' if recursos_html else ''}

    <p>Aproveite! Qualquer dúvida é só chamar 😊</p>
    """

    return await _send_email(
        to=to,
        subject=f"🚀 Upgrade confirmado — Bem-vindo ao {plan_label}!",
        html=_base_html(content),
    )