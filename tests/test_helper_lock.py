"""17 Nov: two PC helpers ran at once (start-up + manual); only one may run."""
from engine.cloud import runner


def test_only_one_helper(monkeypatch):
    monkeypatch.setattr(runner, "_HELPER_LOCK", [])
    assert runner._one_helper(port=47699)
    assert not runner._one_helper(port=47699)
    for s in runner._HELPER_LOCK:
        s.close()


def test_upload_retries_when_another_writer_slipped_in():
    from engine.cloud.store import Store

    class R:
        def __init__(self, code, text=""):
            self.status_code, self.text = code, text

        def json(self):
            return {"ok": True}
    calls = []

    class S:
        def post(self, *a, **k):
            calls.append(1)
            return R(422, '{"code":"already_exists"}') if len(calls) == 1 else R(201)
    st = Store.__new__(Store)
    st.s, st.repo, st.h = S(), "o/r", {}
    st.release = lambda tag: {"id": 1}
    st.delete = lambda tag, name: None
    assert st.put("media", "x.json", b"{}") == {"ok": True} and len(calls) == 2
