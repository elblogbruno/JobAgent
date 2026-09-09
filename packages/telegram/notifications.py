from typing import List, Optional
from packages.domain.models import CanonicalJob, MatchScorecard


class TelegramNotificationFormatter:
    @staticmethod
    def format_submission(
        job: CanonicalJob,
        scorecard: MatchScorecard,
        cv_name: str,
        reactive_resume_app_url: str = "",
    ) -> str:
        strengths_str = "\n".join(f"• {s}" for s in scorecard.strengths[:3]) or "• Strong technical alignment"
        gaps_str = "\n".join(f"• {g}" for g in scorecard.gaps[:2]) or "• None identified"

        return f"""🚀 <b>CANDIDATURA ENVIADA</b>

🏢 <b>Empresa:</b> {job.company}
💼 <b>Puesto:</b> {job.role}
📍 <b>Ubicación:</b> {job.location or 'Not specified'}
🎯 <b>Match:</b> {scorecard.score}/100

🌐 <b>Fuente:</b> {job.source.value.capitalize()}
📄 <b>CV:</b> {cv_name}
✅ <b>Estado:</b> APPLIED

💪 <b>Puntos fuertes:</b>
{strengths_str}

⚠️ <b>Gaps:</b>
{gaps_str}

🔗 <b>Oferta:</b>
{job.canonical_url}

📊 <b>Reactive Resume:</b>
{reactive_resume_app_url or 'Tracked in Reactive Resume'}
"""

    @staticmethod
    def format_review_prompt(
        job: CanonicalJob,
        scorecard: MatchScorecard,
        run_id: str,
    ) -> str:
        strengths_str = "\n".join(f"• {s}" for s in scorecard.strengths[:2]) or "• Strong match"
        return f"""📋 <b>NUEVA CANDIDATURA PREPARADA PARA REVISIÓN</b>

🏢 <b>Empresa:</b> {job.company}
💼 <b>Puesto:</b> {job.role}
🎯 <b>Match Score:</b> {scorecard.score}/100

💪 <b>Destacado:</b>
{strengths_str}

🔗 <b>Oferta:</b> {job.canonical_url}

<i>¿Deseas autorizar el envío automático de esta candidatura?</i>
"""

    @staticmethod
    def format_blocked_alert(
        job: CanonicalJob,
        reason: str,
        details: str = "",
    ) -> str:
        return f"""🚨 <b>CANDIDATURA BLOQUEADA ({reason})</b>

🏢 <b>Empresa:</b> {job.company}
💼 <b>Puesto:</b> {job.role}
⚠️ <b>Motivo:</b> Se detectó verificación interactiva (CAPTCHA / 2FA / Login requerido).
El agente no evade estas protecciones y ha guardado la sesión de forma segura.

🔗 <b>Completar manualmente en:</b>
{job.apply_url}
"""

    @staticmethod
    def format_manual_question_alert(
        job: CanonicalJob,
        question_text: str,
        run_id: str,
    ) -> str:
        return f"""❓ <b>INFORMACIÓN REQUERIDA (Job Agent)</b>

Para postular a <b>{job.company} — {job.role}</b>, el formulario requiere un dato no especificado en tu perfil:

<i>"{question_text}"</i>

Responde a este mensaje o actualiza el portal para continuar.
"""
