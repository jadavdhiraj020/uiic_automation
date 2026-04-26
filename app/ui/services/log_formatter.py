import html


def format_log_html(raw_message: str, ts: str) -> str:
    """Map log content to deterministic UI color styling."""
    msg = "" if raw_message is None else str(raw_message)
    is_bold = False

    if any(c in msg for c in ("╔", "╗", "╚", "╝", "╠", "╣")):
        color = "#FBBF24"
        is_bold = True
    elif "║" in msg:
        if any(x in msg for x in ("🎉", "COMPLETE")):
            color = "#4ADE80"
        elif any(x in msg for x in ("🚀", "AUTOMATION")):
            color = "#7C83FF"
        else:
            color = "#E2E8F0"
    elif "━" in msg:
        color = "#A78BFA"
        is_bold = True
    elif "STEP" in msg and "/" in msg:
        color = "#E2E8F0"
        is_bold = True
    elif any(x in msg for x in ("✅", "successful", "complete", "found")):
        color = "#4ADE80"
    elif any(x in msg for x in ("❌", "ERROR", "FAILED", "failed")):
        color = "#F87171"
    elif any(x in msg for x in ("⚠️", "warning", "⚠", "MISS")):
        color = "#FBBF24"
    elif any(x in msg for x in ("⏭️", "skipped", "SKIPPED")):
        color = "#94A3B8"
    elif any(x in msg for x in ("⏱️", "Duration")):
        color = "#38BDF8"
    elif any(x in msg for x in ("🎉", "COMPLETE")):
        color = "#4ADE80"
    elif any(x in msg for x in ("📤", "📊", "📁", "🔩", "🔧", "🚀", "📋", "📎", "📌", "🔎", "✏️", "💰", "💼", "🧾", "👷", "✍️", "📝")):
        color = "#7C83FF"
    elif any(x in msg for x in ("🔄", "🔑", "📷", "🌐", "🔘")):
        color = "#94A3B8"
    elif "═" in msg:
        color = "#FBBF24"
        is_bold = True
    else:
        color = "#CBD5E1"

    display_message = html.escape(msg)
    if is_bold:
        display_message = f"<b>{display_message}</b>"

    return (
        f'<span style="color:#94A3B8; font-size:8pt;">[{ts}]</span>'
        f'&nbsp;<span style="color:{color};">{display_message}</span>'
    )
