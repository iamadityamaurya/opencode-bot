import asyncio
import logging
import signal
import sys
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

from opencode_telegram.config import Config
from opencode_telegram.opencode.client import OpenCodeClient
from opencode_telegram.opencode.events import SSEEventListener
from opencode_telegram.opencode.router import EventRouter
from opencode_telegram.storage.database import Database
from opencode_telegram.storage.repositories import Repository
from opencode_telegram.services.projects import ProjectService
from opencode_telegram.services.sessions import SessionService
from opencode_telegram.services.tasks import TaskService
from opencode_telegram.services.heartbeat import HeartbeatService
from opencode_telegram.bot.callbacks import CallbackRegistry
from opencode_telegram.bot.notifier import TelegramNotifier
from opencode_telegram.bot.handlers import BotHandlers

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("opencode_telegram")

# httpx/httpcore log full request URLs at INFO. The Telegram Bot API URL embeds
# the bot token, so never let those log records reach stdout/journald.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

async def async_main():
    # 1. Load configuration
    try:
        config = Config.load()
    except Exception as e:
        logger.critical(f"Configuration error: {e}")
        sys.exit(1)

    logging.getLogger().setLevel(config.log_level)
    logger.info(f"Starting OpenCode Telegram Remote Controller (Database: {config.database_path})")

    # 2. Initialize database & repositories
    db = Database(config.database_path)
    await db.connect()
    repo = Repository(db)

    # 3. Initialize OpenCode Client (V2 API, HTTP basic auth)
    client = OpenCodeClient(
        config.opencode_base_url,
        password=config.opencode_password,
        username=config.opencode_username,
        timeout=config.request_timeout_seconds,
        connect_timeout=config.connect_timeout_seconds,
    )

    # 4. Initialize services
    project_service = ProjectService(config)
    session_service = SessionService(client, repo)

    # Event router: the single fan-out point for the OpenCode SSE stream.
    router = EventRouter()
    callbacks = CallbackRegistry()
    notifier = TelegramNotifier(client, repo, router, callbacks, config)
    heartbeat = HeartbeatService(repo, router, config)
    router.subscribe(notifier.handle_event)
    router.subscribe(heartbeat.handle_event)

    task_service = TaskService(
        client,
        repo,
        poll_interval_seconds=float(config.progress_interval_seconds),
        task_timeout_seconds=config.task_timeout_seconds,
        router=router,
    )

    # 5. Initialize SSE Event Listener
    sse_listener = SSEEventListener(
        config.opencode_base_url,
        password=config.opencode_password,
        username=config.opencode_username,
    )
    sse_listener.add_callback(router.handle)
    await sse_listener.start()

    # 6. Initialize Bot Handlers
    bot_handlers = BotHandlers(
        config=config,
        client=client,
        repo=repo,
        project_service=project_service,
        session_service=session_service,
        task_service=task_service,
        callbacks=callbacks,
        notifier=notifier,
    )

    # 7. Build Telegram Application
    application = (
        Application.builder()
        .token(config.telegram_token)
        .build()
    )

    # Register Command Handlers
    application.add_handler(CommandHandler("start", bot_handlers.start_command))
    application.add_handler(CommandHandler("help", bot_handlers.help_command))
    application.add_handler(CommandHandler("projects", bot_handlers.projects_command))
    application.add_handler(CommandHandler("project", bot_handlers.project_select_command))
    application.add_handler(CommandHandler("chats", bot_handlers.active_chats_command))
    application.add_handler(CommandHandler("active", bot_handlers.active_chats_command))
    application.add_handler(CommandHandler("new", bot_handlers.new_session_command))
    application.add_handler(CommandHandler("sessions", bot_handlers.sessions_command))
    application.add_handler(CommandHandler("session", bot_handlers.session_select_command))
    application.add_handler(CommandHandler("ask", bot_handlers.ask_command))
    application.add_handler(CommandHandler("status", bot_handlers.status_command))
    application.add_handler(CommandHandler("stop", bot_handlers.stop_command))
    application.add_handler(CommandHandler("diff", bot_handlers.diff_command))
    application.add_handler(CommandHandler("history", bot_handlers.history_command))
    application.add_handler(CommandHandler("health", bot_handlers.health_command))
    application.add_handler(CommandHandler("agent", bot_handlers.agent_command))
    application.add_handler(CommandHandler("models", bot_handlers.models_command))
    application.add_handler(CommandHandler("model", bot_handlers.models_command))
    application.add_handler(CommandHandler("rename", bot_handlers.rename_command))

    # Register Callback Query Handler & Plain Text / Media Message Handlers
    application.add_handler(CallbackQueryHandler(bot_handlers.callback_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot_handlers.ask_command))
    application.add_handler(MessageHandler(filters.VOICE, bot_handlers.voice_handler))
    application.add_handler(MessageHandler(filters.Document.ALL, bot_handlers.document_handler))

    logger.info("Bot application initialized. Starting polling...")

    # Run bot polling loop
    async with application:
        await application.start()
        notifier.bind(application.bot)
        heartbeat.bind(application.bot)
        heartbeat.start()
        await application.updater.start_polling()

        # Keep running until interrupt signal
        stop_event = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop_event.set)

        await stop_event.wait()

        logger.info("Stopping bot polling...")
        await heartbeat.stop()
        await sse_listener.stop()
        await application.updater.stop()
        await application.stop()
        await client.close()
        await db.close()

def main():
    try:
        asyncio.run(async_main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped.")

if __name__ == "__main__":
    main()
