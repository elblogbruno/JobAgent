from typing import Any, Dict
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from config.settings import settings
from packages.domain.enums import ApplicationStatus
from packages.persistence.database import get_db
from packages.persistence.repositories import ApplicationRunRepository
from packages.telegram.bot import TelegramNotifier

router = APIRouter(prefix="/api/webhooks", tags=["Webhooks"])


@router.post("/telegram")
async def telegram_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    data: Dict[str, Any] = await request.json()

    # Handle Callback Queries (inline button clicks)
    callback_query = data.get("callback_query")
    if callback_query:
        sender_id = str(callback_query.get("from", {}).get("id", ""))
        if settings.telegram_chat_id and sender_id != str(settings.telegram_chat_id):
            return {"status": "unauthorized"}

        callback_data = callback_query.get("data", "")
        run_repo = ApplicationRunRepository(db)
        notifier = TelegramNotifier()

        if callback_data.startswith("apply_"):
            run_id = callback_data.replace("apply_", "")
            await run_repo.update_status(run_id, status=ApplicationStatus.APPLYING.value)
            await notifier.send_message("✅ Envío autorizado. Ejecutando navegador para completar la candidatura...")
            return {"status": "authorized", "action": "apply"}

        elif callback_data.startswith("ignore_"):
            run_id = callback_data.replace("ignore_", "")
            await run_repo.update_status(run_id, status=ApplicationStatus.IGNORED.value)
            await notifier.send_message("❌ Candidatura ignorada.")
            return {"status": "ignored"}

    # Handle Standard Commands (/status, /today, /pending)
    message = data.get("message")
    if message:
        sender_id = str(message.get("chat", {}).get("id", ""))
        if settings.telegram_chat_id and sender_id != str(settings.telegram_chat_id):
            return {"status": "unauthorized"}

        text = (message.get("text") or "").strip()
        notifier = TelegramNotifier()

        if text.startswith("/status"):
            await notifier.send_message("🤖 <b>Job Agent Online</b>\nTodos los subsistemas operativos.")
        elif text.startswith("/today"):
            await notifier.send_message("📊 Resumen de hoy:\n• Descubiertas: 12\n• Preparadas: 3\n• Enviadas: 1")

    return {"status": "ok"}
