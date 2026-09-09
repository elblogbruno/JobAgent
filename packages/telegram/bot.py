from typing import Any, Dict, List, Optional
import httpx
from config.settings import settings
from packages.domain.models import CanonicalJob, MatchScorecard
from packages.telegram.notifications import TelegramNotificationFormatter


class TelegramNotifier:
    def __init__(
        self,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None,
        timeout: float = 15.0
    ):
        self.bot_token = bot_token or settings.telegram_bot_token
        self.chat_id = chat_id or settings.telegram_chat_id
        self.timeout = timeout
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}" if self.bot_token else None

    async def send_message(
        self,
        text: str,
        reply_markup: Optional[Dict[str, Any]] = None,
        parse_mode: str = "HTML",
    ) -> bool:
        if not self.base_url or not self.chat_id:
            # Silently succeed in development if token is unconfigured
            return True

        url = f"{self.base_url}/sendMessage"
        payload: Dict[str, Any] = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": False,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                resp = await client.post(url, json=payload)
                return resp.is_success
            except Exception:
                return False

    async def notify_submission(
        self,
        job: CanonicalJob,
        scorecard: MatchScorecard,
        cv_name: str,
        reactive_resume_app_url: str = "",
    ) -> bool:
        text = TelegramNotificationFormatter.format_submission(
            job=job,
            scorecard=scorecard,
            cv_name=cv_name,
            reactive_resume_app_url=reactive_resume_app_url,
        )
        return await self.send_message(text)

    async def notify_review_prompt(
        self,
        job: CanonicalJob,
        scorecard: MatchScorecard,
        run_id: str,
    ) -> bool:
        text = TelegramNotificationFormatter.format_review_prompt(job, scorecard, run_id)
        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "✅ Aplicar", "callback_data": f"apply_{run_id}"},
                    {"text": "📄 Ver Oferta", "url": job.canonical_url},
                    {"text": "❌ Ignorar", "callback_data": f"ignore_{run_id}"},
                ]
            ]
        }
        return await self.send_message(text, reply_markup=keyboard)

    async def notify_blocked(
        self,
        job: CanonicalJob,
        reason: str,
        details: str = "",
    ) -> bool:
        text = TelegramNotificationFormatter.format_blocked_alert(job, reason, details)
        return await self.send_message(text)

    async def notify_manual_question(
        self,
        job: CanonicalJob,
        question_text: str,
        run_id: str,
    ) -> bool:
        text = TelegramNotificationFormatter.format_manual_question_alert(job, question_text, run_id)
        return await self.send_message(text)
