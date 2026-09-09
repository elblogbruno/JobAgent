from datetime import datetime
from typing import List, Optional
import httpx
from packages.reactive_resume.client import ReactiveResumeClient
from packages.reactive_resume.models import ApplicationResponse
from packages.telegram.bot import TelegramNotifier


class ApplicationMonitor:
    def __init__(
        self,
        rr_client: ReactiveResumeClient,
        telegram_notifier: Optional[TelegramNotifier] = None
    ):
        self.rr_client = rr_client
        self.notifier = telegram_notifier or TelegramNotifier()

    async def check_follow_ups(self) -> List[ApplicationResponse]:
        """
        Scans Reactive Resume for applications where followUpAt <= today.
        """
        now = datetime.utcnow()
        due_follow_ups: List[ApplicationResponse] = []
        try:
            apps = await self.rr_client.list_applications()
            for app in apps:
                if app.status == "applied" and app.followUpAt and app.followUpAt <= now:
                    due_follow_ups.append(app)
                    await self._notify_follow_up(app)
        except Exception:
            pass

        return due_follow_ups

    async def check_job_link_health(self, job_url: str) -> bool:
        """
        Returns False if the job URL responds with 404/410, meaning posting was taken down.
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.head(job_url, follow_redirects=True)
                return resp.status_code < 400
        except Exception:
            return True

    async def _notify_follow_up(self, app: ApplicationResponse):
        msg = f"""⏰ <b>RECORDATORIO DE SEGUIMIENTO</b>

🏢 <b>Empresa:</b> {app.company}
💼 <b>Puesto:</b> {app.role}
📅 Han transcurrido los días configurados desde el envío.
Se recomienda enviar un mensaje de seguimiento al reclutador.
"""
        await self.notifier.send_message(msg)
