def split_message(text: str, max_length: int = 4000) -> list[str]:
    """Splits long text into chunks <= max_length at paragraph/newline boundaries."""
    if len(text) <= max_length:
        return [text]

    chunks = []
    lines = text.split("\n")
    current_chunk = ""

    for line in lines:
        if len(current_chunk) + len(line) + 1 > max_length:
            if current_chunk:
                chunks.append(current_chunk)
                current_chunk = ""
            # If a single line exceeds max_length, split it forcibly
            while len(line) > max_length:
                chunks.append(line[:max_length])
                line = line[max_length:]
            current_chunk = line
        else:
            if current_chunk:
                current_chunk += "\n" + line
            else:
                current_chunk = line

    if current_chunk:
        chunks.append(current_chunk)

    return chunks

def format_status_response(
    health: bool,
    project_name: str | None,
    session_id: str | None,
    task_state: str | None,
    last_update: str | None = None
) -> str:
    health_str = "🟢 Online" if health else "🔴 Offline"
    proj_str = project_name or "None selected"
    sess_str = session_id or "None selected"
    task_str = task_state or "Idle"

    return (
        f"🤖 *OpenCode Bot Status*\n\n"
        f"• *Server Health:* {health_str}\n"
        f"• *Active Project:* `{proj_str}`\n"
        f"• *Active Session:* `{sess_str}`\n"
        f"• *Current Task:* `{task_str}`\n"
    )

def format_diff_summary(diff_items: list[dict]) -> str:
    if not diff_items:
        return "ℹ️ No changes recorded for this session."

    output = "📝 *Session Changes Summary*\n\n"
    for item in diff_items:
        filename = item.get("file", item.get("path", "unknown"))
        adds = item.get("additions", 0)
        dels = item.get("deletions", 0)
        output += f"• `{filename}` (+{adds} / -{dels})\n"

    return output
