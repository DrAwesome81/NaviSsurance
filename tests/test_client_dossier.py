from core.client_dossier import get_client_dossier_snapshot
# Client dossier tests validate Pulse private memory and 🛡️ security-relevant intel in client snapshots (dossier tests)
# additional Pulse private memory + Shield for client dossier tests


class _FakeDB:
    def client_get(self, cid):
        if cid == 1:
            return {"id": 1, "name": "Acme Med", "aliases_json": "[]", "domain_rules_json": "[]", "notes": "", "is_active": 1}
        return None

    def user_memory_search_by_entity(self, *, entity_type, entity_key, approval_status=None, limit=10):
        return []

    def cos_get_projects(self, *, client_id=None, **kwargs):
        return [{"id": 10, "name": "Acme QMS", "client_id": 1}]

    def agent_list_assignments(self, **kwargs):
        return [{"id": 5, "title": "Draft proposal", "source_project_id": 10, "status": "queued"}]

    def get_tasks(self):
        return [{"id": 99, "title": "Review docs", "cos_project_id": 10}]


def test_snapshot_basic_shape():
    db = _FakeDB()
    snap = get_client_dossier_snapshot(db, 1)
    assert snap["client_id"] == 1
    assert "profile" in snap
    assert snap["profile"]["name"] == "Acme Med"
    assert isinstance(snap.get("projects"), list)
    assert isinstance(snap.get("assignments"), list)
    assert isinstance(snap.get("tasks"), list)
    assert "memory" in snap


def test_snapshot_normalizes_tuple_projects_like_sqlite():
    """Real cos_get_projects returns tuples; dossier must not assume dict .get."""

    def _row(pid, name="P", client_id=1):
        return (
            pid,
            name,
            "legacy client str",
            None,
            "Active",
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            int(client_id),
        )

    class _TupleProjectDB(_FakeDB):
        def cos_get_projects(self, *, client_id=None, **kwargs):
            if client_id == 1:
                return [_row(10), _row(11)]
            return []

    db = _TupleProjectDB()
    snap = get_client_dossier_snapshot(db, 1)
    assert snap["projects"][0]["id"] == 10
    assert snap["projects"][0]["name"] == "P"
    assert snap["projects"][0]["client_id"] == 1
    assert snap["projects"][1]["id"] == 11


def test_snapshot_includes_client_id_on_projects():
    """Dossier should correctly surface client_id for linked projects."""

    class _ClientProjectDB(_FakeDB):
        def cos_get_projects(self, *, client_id=None, **kwargs):
            if client_id == 1:
                return [(10, "QMS Overhaul", "Acme", None, "Active", 2, "2026-07-15", "Risk review", None, None, None, None, None, None, None, None, None, None, None, None, None, None, 1)]
            return []

    db = _ClientProjectDB()
    snap = get_client_dossier_snapshot(db, 1)
    assert len(snap["projects"]) == 1
    assert snap["projects"][0]["client_id"] == 1
