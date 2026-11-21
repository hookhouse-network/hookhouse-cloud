"""21 Nov (plan 5.10 layer 3): Openverse (CC0 / PDM / CC BY only, credited) and The Met Open Access (public domain)
as extra real-picture sources, because free AI pictures run out by mid-afternoon."""
from engine.media import visuals


class R:
    def __init__(self, data):
        self.data = data

    def json(self):
        return self.data


class S:
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def get(self, url, params=None, timeout=30):
        self.calls.append((url, params))
        for key, data in self.routes.items():
            if key in url:
                return R(data(url) if callable(data) else data)
        return R({})


def test_openverse_keeps_only_owner_allowed_licences_with_credit(monkeypatch):
    res = {"results": [
        {"id": "a", "title": "Old plane", "url": "u1", "license": "by", "license_version": "2.0", "creator": "Ann",
         "width": 1600, "tags": [{"name": "airplane"}]},
        {"id": "b", "title": "Share", "url": "u2", "license": "by-sa", "creator": "Bo", "width": 1600},
        {"id": "c", "title": "NC", "url": "u3", "license": "by-nc", "creator": "Cy", "width": 1600},
        {"id": "d", "title": "Tiny", "url": "u4", "license": "cc0", "creator": "Di", "width": 300},
        {"id": "e", "title": "AI art", "url": "u5", "license": "cc0", "width": 1600, "tags": [{"name": "ai generated"}]}]}
    s = S({"openverse.org": res})
    monkeypatch.setattr(visuals, "session", lambda: s)
    out = visuals.openverse("old plane")
    assert [v.meta["url"] for v in out] == ["u1"]
    assert out[0].license == "CC BY" and "Ann" in out[0].credit and "CC BY 2.0" in out[0].credit
    assert "license" in s.calls[0][1] and "by-sa" not in s.calls[0][1]["license"]


def test_met_uses_the_v1_1_search_and_only_public_domain_objects(monkeypatch):
    objs = {"1": {"isPublicDomain": True, "primaryImage": "img1", "title": "Seated Statue"},
            "2": {"isPublicDomain": False, "primaryImage": "img2", "title": "Loan"}}
    s = S({"v1.1/search": {"objectIDs": [1, 2]}, "/objects/": lambda url: objs[url.rsplit("/", 1)[1]]})
    monkeypatch.setattr(visuals, "session", lambda: s)
    out = visuals.met_museum("statue")
    assert [v.meta["url"] for v in out] == ["img1"] and out[0].license == "CC0"
    assert "v1.1/search" in s.calls[0][0]                      # v1/search was retired on 1 Oct 2026
