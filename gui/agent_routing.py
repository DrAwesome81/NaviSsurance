from __future__ import annotations


def route_for_agent(agent_code: str):
    """
    Return route tuple:
    (tab_attr, group_attr_or_none, console_attr_or_none, tab_label)
    """
    code = (agent_code or "").strip().lower()
    return {
        "atlas": ("deep_research_tab", "atlas_chat_group", "atlas_console", "Deep Research"),
        "quill": ("workspace_tab", "quill_chat_group", "quill_console", "Workspace"),
        "sentinel": ("compliance_tab", "sentinel_chat_group", "sentinel_console", "Compliance"),
        "lex": ("compliance_tab", "lex_chat_group", "lex_console", "Compliance"),
        "scout": ("leads_tab", "scout_chat_group", "scout_console", "Leads"),
        "mason": ("tasks_tab", "mason_chat_group", "mason_console", "Tasks"),
        "ledger": ("billing_tab", None, "ledger_console", "Billing"),
        "archive": ("library_tab", None, "agent_console", "Library"),
        "pulse": ("intel_tab", None, "agent_console", "Intel"),
        "shield": ("security_tab", None, "agent_console", "Security"),
        "navi": ("chief_of_staff_tab", None, None, "Chief of Staff"),
    }.get(code)

