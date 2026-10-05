from telegram import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

def get_main_reply_keyboard() -> ReplyKeyboardMarkup:
    """Persistent bottom reply keyboard for easy quick-access without typing slash commands."""
    keyboard = [
        [KeyboardButton("💬 Active Chats"), KeyboardButton("📁 Projects")],
        [KeyboardButton("➕ New Session"), KeyboardButton("⚙️ Agent Mode")],
        [KeyboardButton("📊 Status"), KeyboardButton("📝 View Diff")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_projects_keyboard(projects: list[str]) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(f"📁 {name}", callback_data=f"select_project:{name}")]
        for name in projects
    ]
    return InlineKeyboardMarkup(buttons)

def get_sessions_keyboard(sessions: list[dict]) -> InlineKeyboardMarkup:
    buttons = []
    for s in sessions[:10]:  # Limit top 10 sessions for UI clarity
        title = s.get("title") or s.get("session_id") or "Untitled"
        sid = s.get("session_id", "")
        buttons.append([InlineKeyboardButton(f"💬 {title[:25]}", callback_data=f"select_session:{sid}")])

    buttons.append([InlineKeyboardButton("➕ New Session", callback_data="action:new_session")])
    return InlineKeyboardMarkup(buttons)

def get_task_actions_keyboard(session_id: str) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton("🔨 Switch to Build", callback_data=f"set_agent:build:{session_id}"),
            InlineKeyboardButton("📝 Switch to Plan", callback_data=f"set_agent:plan:{session_id}"),
        ],
        [
            InlineKeyboardButton("🛑 Stop Task", callback_data=f"stop_task:{session_id}"),
            InlineKeyboardButton("📊 Status", callback_data="action:status"),
        ],
        [InlineKeyboardButton("📝 View Diff", callback_data=f"view_diff:{session_id}")],
    ]
    return InlineKeyboardMarkup(buttons)

def get_permission_keyboard(permission_id: str) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton("✅ Approve", callback_data=f"perm_approve:{permission_id}"),
            InlineKeyboardButton("❌ Deny", callback_data=f"perm_deny:{permission_id}"),
        ]
    ]
    return InlineKeyboardMarkup(buttons)

def get_active_chats_keyboard(active_items: list[dict]) -> InlineKeyboardMarkup:
    buttons = []
    for item in active_items[:10]:
        title = item.get("title") or item.get("session_id", "")[:12]
        sid = item.get("session_id", "")
        buttons.append([
            InlineKeyboardButton(f"👉 Select {title[:20]}", callback_data=f"select_session:{sid}"),
            InlineKeyboardButton("🛑 Stop", callback_data=f"stop_task:{sid}"),
        ])
    return InlineKeyboardMarkup(buttons)

def get_agent_keyboard(session_id: str) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton("🔨 Switch to Build Mode", callback_data=f"set_agent:build:{session_id}"),
            InlineKeyboardButton("📝 Switch to Plan Mode", callback_data=f"set_agent:plan:{session_id}"),
        ]
    ]
    return InlineKeyboardMarkup(buttons)

def get_new_session_folder_keyboard(projects: dict) -> InlineKeyboardMarkup:
    buttons = []
    for name, proj in projects.items():
        is_def = " (Default)" if name in ("code", "default") else ""
        buttons.append([InlineKeyboardButton(f"📁 {name}{is_def} ({proj.path})", callback_data=f"create_new_session:{name}")])
    return InlineKeyboardMarkup(buttons)

