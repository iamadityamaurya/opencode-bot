import logging
from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

def is_user_authorized(user_id: int | None, allowed_user_ids: set[int]) -> bool:
    if user_id is None:
        return False
    return user_id in allowed_user_ids

async def enforce_user_authorization(update: Update, context: ContextTypes.DEFAULT_TYPE, allowed_user_ids: set[int]) -> bool:
    effective_user = update.effective_user
    user_id = effective_user.id if effective_user else None

    if not is_user_authorized(user_id, allowed_user_ids):
        logger.warning(f"Unauthorized access attempt by user {user_id}")
        if update.effective_message:
            await update.effective_message.reply_text("🚫 Access Denied: You are not authorized to use this bot.")
        elif update.callback_query:
            await update.callback_query.answer("🚫 Access Denied", show_alert=True)
        return False
    return True
