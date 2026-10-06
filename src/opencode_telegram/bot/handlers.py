import logging
from telegram import Update
from telegram.ext import ContextTypes
from opencode_telegram.config import Config
from opencode_telegram.bot.authorization import enforce_user_authorization
from opencode_telegram.bot.callbacks import CallbackRegistry
from opencode_telegram.bot.notifier import TelegramNotifier
from opencode_telegram.bot.formatting import format_status_response, format_diff_summary, split_message
from opencode_telegram.bot.keyboards import (
    get_projects_keyboard,
    get_sessions_keyboard,
    get_task_actions_keyboard,
    get_active_chats_keyboard,
    get_agent_keyboard,
    get_main_reply_keyboard,
    get_new_session_folder_keyboard,
    get_models_keyboard,
    get_permission_keyboard,
)
from opencode_telegram.opencode.client import OpenCodeClient
from opencode_telegram.services.projects import ProjectService
from opencode_telegram.services.sessions import SessionService
from opencode_telegram.services.tasks import TaskService
from opencode_telegram.storage.repositories import Repository

logger = logging.getLogger(__name__)

class BotHandlers:
    def __init__(
        self,
        config: Config,
        client: OpenCodeClient,
        repo: Repository,
        project_service: ProjectService,
        session_service: SessionService,
        task_service: TaskService,
        callbacks: CallbackRegistry,
        notifier: TelegramNotifier,
    ):
        self.config = config
        self.client = client
        self.repo = repo
        self.project_service = project_service
        self.session_service = session_service
        self.task_service = task_service
        self.callbacks = callbacks
        self.notifier = notifier

    async def _check_auth(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
        authorized = await enforce_user_authorization(update, context, self.config.allowed_user_ids)
        if authorized and update.effective_user and update.effective_chat:
            # Remember where to deliver proactive messages (completion, permission,
            # heartbeat) for this user.
            try:
                await self.repo.set_user_chat(update.effective_user.id, update.effective_chat.id)
            except Exception as err:
                logger.debug(f"Failed to record chat id: {err}")
        return authorized

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update, context):
            return

        msg = (
            "🚀 *OpenCode Remote Controller*\n\n"
            "Welcome! This bot lets you remotely interact with your local OpenCode instance securely.\n\n"
            "*Available Commands:*\n"
            "• `/projects` - List and select working project\n"
            "• `/chats` or `/active` - Show all active chats & ongoing work\n"
            "• `/new` - Create a new session in current project\n"
            "• `/sessions` - List existing sessions\n"
            "• `/models` - View & switch AI models\n"
            "• `/rename <title>` - Rename current session title\n"
            "• `/ask <prompt>` - Send task to OpenCode\n"
            "• `/status` - Check server health & running task\n"
            "• `/stop` - Abort active task\n"
            "• `/diff` - View file changes\n"
            "• `/history` - View conversation history\n"
            "• `/health` - OpenCode server check\n"
        )
        reply_kb = get_main_reply_keyboard()
        await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=reply_kb)

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.start_command(update, context)

    async def projects_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update, context):
            return

        allowed = self.project_service.get_allowed_projects()
        if not allowed:
            await update.message.reply_text("No projects currently configured.")
            return

        keyboard = get_projects_keyboard(list(allowed.keys()))
        await update.message.reply_text("📁 *Configured Projects:*\nSelect one to work on:", reply_markup=keyboard, parse_mode="Markdown")

    async def project_select_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update, context):
            return

        if not context.args:
            await update.message.reply_text("Usage: `/project <name>`", parse_mode="Markdown")
            return

        proj_name = context.args[0].strip()
        proj = self.project_service.get_project(proj_name)
        if not proj:
            await update.message.reply_text(f"❌ Unknown project '{proj_name}'. Use `/projects` to list allowed projects.")
            return

        user_id = update.effective_user.id
        await self.repo.set_user_project(user_id, proj_name)
        await update.message.reply_text(f"✅ Selected project: *{proj_name}*\nPath: `{proj.path}`", parse_mode="Markdown")

    async def new_session_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update, context):
            return

        user_id = update.effective_user.id
        allowed_projects = self.project_service.get_allowed_projects()

        if context.args:
            proj_name = context.args[0].strip()
            proj = self.project_service.get_project(proj_name)
            if not proj:
                await update.message.reply_text(f"❌ Unknown project/folder '{proj_name}'.")
                return
            await self._create_session_in_project(update, user_id, proj_name, proj)
            return

        keyboard = get_new_session_folder_keyboard(allowed_projects)
        await update.message.reply_text(
            "➕ *Create New Session*\n\n"
            "Select a target project folder for this session:\n"
            "_(Default folder is `code`: `/home/aditys/code`)_",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )

    async def _create_session_in_project(self, update_or_query, user_id: int, proj_name: str, proj):
        try:
            session = await self.session_service.create_session_for_user(
                user_id,
                proj_name,
                directory=str(proj.path)
            )
            msg_text = (
                f"✨ *New OpenCode Session Created!*\n\n"
                f"• *Session ID:* `{session.id}`\n"
                f"• *Project:* `{proj_name}`\n"
                f"• *Directory:* `{proj.path}`\n\n"
                f"Send prompts directly or tap buttons below to start work."
            )
            keyboard = get_task_actions_keyboard(session.id)
            if hasattr(update_or_query, "edit_message_text"):
                await update_or_query.edit_message_text(msg_text, parse_mode="Markdown", reply_markup=keyboard)
            else:
                await update_or_query.message.reply_text(msg_text, parse_mode="Markdown", reply_markup=keyboard)
        except Exception as e:
            logger.error(f"Failed to create session: {e}", exc_info=True)
            err_msg = f"❌ Failed to create session: {e}"
            if hasattr(update_or_query, "edit_message_text"):
                await update_or_query.edit_message_text(err_msg)
            else:
                await update_or_query.message.reply_text(err_msg)

    async def sessions_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update, context):
            return

        user_id = update.effective_user.id
        sessions = await self.session_service.list_user_sessions(user_id)
        if not sessions:
            await update.message.reply_text("ℹ️ No active sessions found. Create one with `/new`.")
            return

        keyboard = get_sessions_keyboard(sessions)
        await update.message.reply_text("💬 *Your OpenCode Sessions:*", reply_markup=keyboard, parse_mode="Markdown")

    async def session_select_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update, context):
            return

        if not context.args:
            await update.message.reply_text("Usage: `/session <session_id>`", parse_mode="Markdown")
            return

        session_id = context.args[0].strip()
        user_id = update.effective_user.id
        await self.repo.set_user_session(user_id, session_id)
        await update.message.reply_text(f"✅ Selected session: `{session_id}`", parse_mode="Markdown")

    async def ask_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update, context):
            return

        prompt = " ".join(context.args).strip() if context.args else ""
        if not prompt and update.message and update.message.text:
            prompt = update.message.text.strip()

        if not prompt:
            await update.message.reply_text("Usage: `/ask <prompt>` or simply type your prompt.", parse_mode="Markdown")
            return

        if prompt in ("💬 Active Chats", "Active Chats"):
            return await self.active_chats_command(update, context)
        elif prompt in ("📁 Projects", "Projects"):
            return await self.projects_command(update, context)
        elif prompt in ("➕ New Session", "New Session"):
            return await self.new_session_command(update, context)
        elif prompt in ("⚙️ Agent Mode", "Agent Mode"):
            return await self.agent_command(update, context)
        elif prompt in ("🤖 AI Models", "AI Models"):
            return await self.models_command(update, context)
        elif prompt in ("📊 Status", "Status"):
            return await self.status_command(update, context)
        elif prompt in ("📝 View Diff", "View Diff"):
            return await self.diff_command(update, context)
        elif prompt in ("📖 History", "History"):
            return await self.history_command(update, context)

        user_id = update.effective_user.id
        state = await self.repo.get_user_state(user_id)
        session_id = state.selected_session_id if state else None

        if not session_id:
            # Auto-create session if none active
            proj_name = state.selected_project if state and state.selected_project else (self.config.default_project or "default")
            proj = self.project_service.get_project(proj_name)
            try:
                session = await self.session_service.create_session_for_user(
                    user_id,
                    proj_name,
                    directory=str(proj.path) if proj else None,
                )
                session_id = session.id
            except Exception as err:
                await update.message.reply_text(f"❌ Failed to initialize session: {err}")
                return

        # Acknowledge prompt submission
        ack_msg = await update.message.reply_text(
            f"⚡ *Task Submitted*\nSession: `{session_id[:12]}...`\n\n_Processing prompt with OpenCode..._",
            parse_mode="Markdown"
        )
        chat_id = update.effective_chat.id
        self.notifier.register_task_message(session_id, chat_id, ack_msg.message_id)

        async def on_complete(task_rec):
            self.notifier.clear_task_message(session_id)
            keyboard = get_task_actions_keyboard(session_id)
            if task_rec.state == "completed":
                chunks = split_message(task_rec.response_text or "Task completed successfully.")
                for chunk in chunks:
                    await update.effective_chat.send_message(chunk, parse_mode="Markdown", reply_markup=keyboard)
            elif task_rec.state == "cancelled":
                await update.effective_chat.send_message("🛑 Task was cancelled by user.", reply_markup=keyboard)
            else:
                err_text = task_rec.response_text or "Task failed."
                await update.effective_chat.send_message(f"❌ Task Failed:\n`{err_text}`", parse_mode="Markdown", reply_markup=keyboard)

        try:
            await self.task_service.submit_task(
                user_id,
                session_id,
                prompt,
                on_completion=on_complete,
                chat_id=chat_id,
                ack_message_id=ack_msg.message_id,
            )
        except Exception as e:
            self.notifier.clear_task_message(session_id)
            await ack_msg.edit_text(f"❌ Error submitting task: {e}")

    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update, context):
            return

        user_id = update.effective_user.id
        health = await self.client.check_health()
        state = await self.repo.get_user_state(user_id)
        proj = state.selected_project if state else None
        sess = state.selected_session_id if state else None

        active_task = await self.repo.get_active_task_for_session(sess) if sess else None
        task_str = active_task.state if active_task else "Idle"

        text = format_status_response(health, proj, sess, task_str)
        await update.message.reply_text(text, parse_mode="Markdown")

    async def stop_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update, context):
            return

        user_id = update.effective_user.id
        state = await self.repo.get_user_state(user_id)
        sess = state.selected_session_id if state else None

        if not sess:
            await update.message.reply_text("⚠️ No active session selected.")
            return

        stopped = await self.task_service.cancel_task(sess)
        if stopped:
            await update.message.reply_text(f"🛑 Requested cancellation for session `{sess}`.", parse_mode="Markdown")
        else:
            await update.message.reply_text("ℹ️ No active task running in selected session.")

    async def diff_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update, context):
            return

        user_id = update.effective_user.id
        state = await self.repo.get_user_state(user_id)
        sess = state.selected_session_id if state else None

        if not sess:
            await update.message.reply_text("⚠️ No active session selected.")
            return

        diffs = await self.client.get_diff(sess)
        text = format_diff_summary(diffs)
        await update.message.reply_text(text, parse_mode="Markdown")

    async def history_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update, context):
            return

        user_id = update.effective_user.id
        state = await self.repo.get_user_state(user_id)
        sess = state.selected_session_id if state else None

        if not sess:
            await update.message.reply_text("⚠️ No active session selected.")
            return

        try:
            msgs = await self.client.get_messages(sess)
            if not msgs:
                await update.message.reply_text("ℹ️ No message history found for this session.")
                return

            out = f"📖 *Session History (`{sess[:10]}...`)*\n\n"
            for m in reversed(msgs[:6]):
                if m.msg_type == "user":
                    out += f"👤 *User:* {m.text[:300]}\n\n"
                elif m.msg_type == "assistant":
                    out += f"🤖 *Assistant:* {m.text[:300]}\n\n"

            await update.message.reply_text(out, parse_mode="Markdown")
        except Exception as e:
            await update.message.reply_text(f"❌ Failed to fetch history: {e}")

    async def health_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update, context):
            return

        health = await self.client.check_health()
        status_text = "🟢 OpenCode Server is HEALTHY & REACHABLE." if health else "🔴 OpenCode Server is UNREACHABLE."
        await update.message.reply_text(status_text)

    async def active_chats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update, context):
            return

        try:
            db_tasks = await self.repo.list_all_active_tasks()
            active_task_map = {t.session_id: t for t in db_tasks}

            all_sessions = await self.client.list_sessions()
            if not all_sessions:
                await update.message.reply_text("ℹ️ No active OpenCode sessions found.")
                return

            text = "💬 *OpenCode Active Work & Sessions*\n\n"
            keyboard_items = []

            for i, s in enumerate(all_sessions[:10], 1):
                s_title = s.title or s.directory or s.id
                task = active_task_map.get(s.id)
                status_icon = "⚙️ *WORK IN PROGRESS*" if task else "🟢 Idle"

                text += f"*{i}. {s_title}*\n"
                text += f"   • *Session ID:* `{s.id}`\n"
                if s.directory:
                    text += f"   • *Directory:* `{s.directory}`\n"
                text += f"   • *Status:* {status_icon}\n"
                if task:
                    text += f"   • *Task:* `{task.prompt[:60]}`\n"
                text += "\n"

                keyboard_items.append({
                    "title": s_title,
                    "session_id": s.id
                })

            keyboard = get_active_chats_keyboard(keyboard_items)
            await update.message.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)

        except Exception as e:
            logger.error(f"Failed to fetch active chats: {e}", exc_info=True)
            await update.message.reply_text(f"❌ Failed to fetch active chats: {e}")

    async def agent_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update, context):
            return

        user_id = update.effective_user.id
        state = await self.repo.get_user_state(user_id)
        sess = state.selected_session_id if state else None

        if not sess:
            await update.message.reply_text("⚠️ No active session selected. Select one with `/sessions` or create one with `/new`.")
            return

        target_agent = context.args[0].lower().strip() if context.args else None

        if target_agent in ("build", "plan"):
            success = await self.client.set_session_agent(sess, target_agent)
            if success:
                icon = "🔨" if target_agent == "build" else "📝"
                await update.message.reply_text(f"✅ Switched session agent mode to *{target_agent.upper()}* {icon}", parse_mode="Markdown")
            else:
                await update.message.reply_text(f"❌ Failed to switch agent mode to `{target_agent}`.")
        else:
            keyboard = get_agent_keyboard(sess)
            await update.message.reply_text(
                f"⚙️ *OpenCode Agent Mode Selector*\nSession: `{sess[:12]}...`\n\n"
                f"Usage: `/agent build` or `/agent plan`\nOr choose an option below:",
                reply_markup=keyboard,
                parse_mode="Markdown"
            )

    async def models_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update, context):
            return

        user_id = update.effective_user.id
        state = await self.repo.get_user_state(user_id)
        sess = state.selected_session_id if state else None

        if not sess:
            await update.message.reply_text("⚠️ No active session selected. Select one with `/sessions` or create one with `/new`.")
            return

        models = await self.client.get_models()
        keyboard = get_models_keyboard(models, sess, self.callbacks)
        await update.message.reply_text(
            f"🤖 *OpenCode AI Model Selector*\nSession: `{sess[:12]}...`\n\n"
            f"Select an AI model provider for this session:",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )

    async def rename_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update, context):
            return

        user_id = update.effective_user.id
        state = await self.repo.get_user_state(user_id)
        sess = state.selected_session_id if state else None

        if not sess:
            await update.message.reply_text("⚠️ No active session selected.")
            return

        if not context.args:
            await update.message.reply_text("Usage: `/rename <new session title>`", parse_mode="Markdown")
            return

        new_title = " ".join(context.args).strip()
        success = await self.client.rename_session(sess, new_title)
        if success:
            proj_name = state.selected_project or "default"
            await self.repo.save_session(sess, proj_name, user_id, new_title)
            await update.message.reply_text(f"✅ Session `{sess[:12]}...` renamed to: *{new_title}*", parse_mode="Markdown")
        else:
            await update.message.reply_text(f"❌ Failed to rename session `{sess[:12]}...`.")

    async def voice_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update, context):
            return

        voice = update.message.voice
        if not voice:
            return

        duration = voice.duration
        msg = f"🎙️ *Voice Prompt Received* ({duration}s)\n_Forwarding prompt to OpenCode..._"
        await update.message.reply_text(msg, parse_mode="Markdown")

        caption = update.message.caption or f"Voice task execution request ({duration}s recording)"
        context.args = caption.split()
        await self.ask_command(update, context)

    async def document_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update, context):
            return

        doc = update.message.document
        if not doc:
            return

        file_name = doc.file_name or "uploaded_file"
        caption = update.message.caption or f"Analyze and process attached file: {file_name}"

        prompt_text = f"📎 [File Context: {file_name}]\n\n{caption}"
        context.args = prompt_text.split()
        await self.ask_command(update, context)

    async def callback_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update, context):
            return

        query = update.callback_query
        await query.answer()
        data = query.data
        user_id = update.effective_user.id

        if data.startswith("select_project:"):
            proj_name = data.split(":", 1)[1]
            await self.repo.set_user_project(user_id, proj_name)
            await query.edit_message_text(f"✅ Selected project: *{proj_name}*", parse_mode="Markdown")

        elif data.startswith("select_session:"):
            sid = data.split(":", 1)[1]
            await self.repo.set_user_session(user_id, sid)
            await query.edit_message_text(f"✅ Selected session: `{sid}`", parse_mode="Markdown")

        elif data == "action:new_session":
            allowed_projects = self.project_service.get_allowed_projects()
            keyboard = get_new_session_folder_keyboard(allowed_projects)
            await query.edit_message_text(
                "➕ *Create New Session*\n\n"
                "Select a target project folder for this session:\n"
                "_(Default folder is `code`: `/home/aditys/code`)_",
                reply_markup=keyboard,
                parse_mode="Markdown"
            )

        elif data.startswith("create_new_session:"):
            proj_name = data.split(":", 1)[1]
            proj = self.project_service.get_project(proj_name)
            if not proj:
                await query.edit_message_text(f"❌ Unknown project '{proj_name}'.")
                return
            await self._create_session_in_project(query, user_id, proj_name, proj)

        elif data.startswith("stop_task:"):
            sid = data.split(":", 1)[1]
            await self.task_service.cancel_task(sid)
            await query.edit_message_text(f"🛑 Requested cancellation for session `{sid}`.", parse_mode="Markdown")

        elif data == "action:status":
            health = await self.client.check_health()
            state = await self.repo.get_user_state(user_id)
            proj = state.selected_project if state else None
            sess = state.selected_session_id if state else None
            text = format_status_response(health, proj, sess, "Checked via button")
            await query.edit_message_text(text, parse_mode="Markdown")

        elif data.startswith("view_diff:"):
            sid = data.split(":", 1)[1]
            diffs = await self.client.get_diff(sid)
            text = format_diff_summary(diffs)
            await query.edit_message_text(text, parse_mode="Markdown")

        elif data.startswith("set_agent:"):
            parts = data.split(":")
            agent_name = parts[1]
            sid = parts[2]
            success = await self.client.set_session_agent(sid, agent_name)
            if success:
                icon = "🔨" if agent_name == "build" else "📝"
                await query.edit_message_text(f"✅ Switched session agent mode to *{agent_name.upper()}* {icon}", parse_mode="Markdown")
            else:
                await query.edit_message_text(f"❌ Failed to switch agent mode to `{agent_name}`.")

        elif data.startswith("select_model_menu:"):
            sid = data.split(":", 1)[1]
            models = await self.client.get_models()
            keyboard = get_models_keyboard(models, sid, self.callbacks)
            await query.edit_message_text(
                f"🤖 *Select AI Model for Session*\nSession: `{sid[:12]}...`",
                reply_markup=keyboard,
                parse_mode="Markdown"
            )

        elif data.startswith("model:"):
            token = data.split(":", 1)[1]
            payload = self.callbacks.resolve(token, expected_kind="model")
            if not payload:
                await query.edit_message_text("⌛ This model selection expired. Run /models again.")
                return
            ok = await self.client.set_session_model(
                payload["session_id"],
                payload["model_id"],
                provider_id=payload["provider_id"],
            )
            if ok:
                await query.edit_message_text(
                    f"✅ Switched session model to *{payload['model_id']}*", parse_mode="Markdown"
                )
            else:
                await query.edit_message_text(f"❌ Failed to set model to `{payload['model_id']}`.")

        elif data.startswith("perm:"):
            parts = data.split(":", 2)
            token = parts[1] if len(parts) > 1 else ""
            action = parts[2] if len(parts) > 2 else "approve"
            payload = self.callbacks.resolve(token, expected_kind="permission")
            if not payload:
                await query.edit_message_text("⌛ This permission request expired.")
                return
            approved = (action == "approve")
            await self.client.respond_to_permission(
                payload["session_id"], payload["permission_id"], approved
            )
            status_str = "APPROVED ✅" if approved else "DENIED ❌"
            await query.edit_message_text(f"🛡️ Permission request *{status_str}*", parse_mode="Markdown")


