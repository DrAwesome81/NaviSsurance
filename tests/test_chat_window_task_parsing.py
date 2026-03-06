from gui.chat_window import extract_pipe_tasks


def test_extract_pipe_tasks_parses_single_line_repeated_priority_payload():
    response = (
        "Understood—repeating the shortened to-do list once more for your formatting check. "
        "(No changes or additions made; this is identical to the previous versions.) "
        "### High Priority (Today/Tomorrow - Unblock Progress) "
        "- CoDentist: Create shared folder, add current docs + draft hazard analysis | 03-02-2026 | Business "
        "- Dova: Push Animesh/Ben on CAPAs/DHF progress and ask about design review delay | 03-03-2026 | Business "
        "- Peritia: Ping on SoW status for P5 Design's device | 03-03-2026 | Business "
        "- Blue Goat Cyber: Ping rep on partnership deal status | 03-03-2026 | Business "
        "### Medium Priority (This Week - Advance Projects) "
        "- HippoClinic: Check in with Fei on testing status | 03-04-2026 | Business "
        "- Dova: Research simple de novo submission process for dovavision to speed authorization | 03-06-2026 | Business "
        "- iQSurgical: Reach out to KK for study design help; start drafting pre-submission | 03-06-2026 | Business "
        "### Low Priority (Fit Around Family - Non-Urgent) "
        "- Call plumber | 03-04-2026 | Personal "
        "- Call foundation repair guy | 03-04-2026 | Personal "
        "If everything looks good or you need adjustments, just say the word. "
        "— *Added 9 task(s) to your dashboard.*"
    )
    tasks = extract_pipe_tasks(response)
    assert len(tasks) == 9
    task_texts = {t[0] for t in tasks}
    assert "CoDentist: Create shared folder, add current docs + draft hazard analysis" in task_texts
    assert "Call foundation repair guy" in task_texts
