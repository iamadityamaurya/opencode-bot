from dataclasses import dataclass, field
from typing import Any

@dataclass
class SessionInfo:
    id: str
    project_id: str | None = None
    title: str | None = None
    directory: str | None = None
    created_at: int | None = None
    updated_at: int | None = None
    raw_data: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SessionInfo":
        time_info = data.get("time", {})
        loc = data.get("location", {})
        return cls(
            id=data.get("id", ""),
            project_id=data.get("projectID"),
            title=data.get("title"),
            directory=loc.get("directory") if isinstance(loc, dict) else None,
            created_at=time_info.get("created"),
            updated_at=time_info.get("updated"),
            raw_data=data,
        )

@dataclass
class MessageContentPart:
    type: str
    text: str = ""

@dataclass
class SessionMessage:
    id: str
    session_id: str | None
    msg_type: str  # "user", "assistant", "idle"
    text: str = ""
    reasoning: str = ""
    outcome: str | None = None  # "succeeded", "failed", "interrupted"
    created_at: int | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any], default_session_id: str | None = None) -> "SessionMessage":
        msg_id = data.get("id", "")
        msg_type = data.get("type", "")
        time_info = data.get("time", {})
        created_at = time_info.get("created") if isinstance(time_info, dict) else None
        outcome = data.get("outcome")

        text_content = ""
        reasoning_content = ""

        if msg_type == "user":
            text_content = data.get("text", "")
            if not text_content and isinstance(data.get("payload"), dict):
                text_content = data["payload"].get("text", "")
        elif msg_type == "assistant":
            content_list = data.get("content", [])
            if isinstance(content_list, list):
                for part in content_list:
                    if isinstance(part, dict):
                        p_type = part.get("type")
                        p_text = part.get("text", "")
                        if p_type == "text":
                            text_content += p_text
                        elif p_type == "reasoning":
                            reasoning_content += p_text

        return cls(
            id=msg_id,
            session_id=data.get("sessionID", default_session_id),
            msg_type=msg_type,
            text=text_content,
            reasoning=reasoning_content,
            outcome=outcome,
            created_at=created_at,
        )

@dataclass
class DiffSummary:
    file: str
    additions: int = 0
    deletions: int = 0

@dataclass
class ServerEvent:
    id: str
    event_type: str
    data: dict[str, Any]
    session_id: str | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ServerEvent":
        evt_data = payload.get("data", {})
        sess_id = evt_data.get("sessionID") if isinstance(evt_data, dict) else None
        return cls(
            id=payload.get("id", ""),
            event_type=payload.get("type", "unknown"),
            data=evt_data if isinstance(evt_data, dict) else {},
            session_id=sess_id,
        )
