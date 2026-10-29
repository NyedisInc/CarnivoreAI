
from __future__ import annotations

from src.core.companies import hero_art_gen, hero_art_prompt, hero_images

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
UPLOAD = b"\xff\xd8\xff\xe0" + b"UPLOADED" * 8
FAKE_SECRET = "gh" + "p_" + "Xq7Lm2Zp9Rk4Vb8Nc3Jd6Hf1Gs5Tw0Ya4Qe9"


class FakeProvider:

    def __init__(self, fail=False, theme="a silver sword over a burning server rack"):
        self.fail, self.theme, self.prompts, self.summaries = fail, theme, [], []

    def distill(self, name, summary, avoid=""):
        self.summaries.append(summary)
        self.calls = getattr(self, "calls", []) + [(name, summary, avoid)]
        return self.theme, 0.001

    def image(self, prompt):
        self.prompts.append(prompt)
        if self.fail:
            raise hero_art_gen.ArtError("boom")
        return PNG, 0.04


def test_upload_wins_prompt_has_name_not_secrets_and_failure_keeps_fallback(world):
    kind, rid = hero_images.PROJECT, 7
    hero_images.store(kind, rid, "jpg", UPLOAD)
    fake = FakeProvider()
    for regenerate in (False, True):
        assert hero_art_gen.generate(kind, rid, "Orchard", "a SIEM", fake, regenerate=regenerate)["status"] == "upload"
    assert fake.prompts == [] and hero_images.find(kind, rid).read_bytes() == UPLOAD
    hero_images.remove_upload(kind, rid)
    assert hero_images.find(kind, rid) is None
    bad = FakeProvider(fail=True)
    assert hero_art_gen.generate(kind, rid, "Orchard", "", bad)["status"] == "failed"
    assert len(bad.prompts) == hero_art_gen.ATTEMPTS and hero_images.find(kind, rid) is None
    assert hero_images.index(kind) == {}
    ok = FakeProvider(theme=f"a dragon guarding {FAKE_SECRET}")
    assert hero_art_gen.generate(kind, rid, 'Ac"me Co', "a README", ok)["status"] == "generated"
    prompt = ok.prompts[0]
    assert "Acme Co" in prompt and FAKE_SECRET not in prompt and not hero_art_prompt.has_secret(prompt)
    assert hero_images.find(kind, rid).read_bytes() == PNG and hero_images.fields(kind, rid)["has_image"] is True
    assert (hero_images.generated_dir(kind) / f"{rid}.prompt.json").is_file()
    hero_images.store(kind, rid, "jpg", UPLOAD)
    assert hero_images.find(kind, rid).read_bytes() == UPLOAD
    hero_images.remove_upload(kind, rid)
    assert hero_images.find(kind, rid).read_bytes() == PNG


def test_summary_skips_a_source_that_looks_like_a_secret(tmp_path):
    (tmp_path / "README.md").write_text(f"# Acme\nA billing tool. key={FAKE_SECRET}\n")
    (tmp_path / "package.json").write_text('{"description": "Invoices for plumbers"}')
    assert hero_art_prompt.read_summary(str(tmp_path)) == "Invoices for plumbers"


def test_prompts_are_text_free_logo_or_project_and_the_request_is_landscape():
    for kind, marker in (("project", "intelligence-agency"), ("company", "logo MARK")):
        prompt = hero_art_prompt.build_prompt(kind, "a silver sword")
        assert marker in prompt and "a silver sword" in prompt
        assert "ABSOLUTELY NO text" in prompt and "spelling" not in prompt and "logotype" not in prompt
        assert "centred" in prompt
        big = kind == "company"
        assert ("70 to 80 percent of the frame height" in prompt) is big
        assert ("panorama" in prompt and "28% of the frame height" in prompt) is not big
    assert "no wordmark" in hero_art_prompt.build_prompt("company", None, "Acme")
    sent = {}

    class Capture(hero_art_gen.OpenRouterArt):
        def _post(self, path, body, timeout):
            sent.update(body)
            return {"data": [{"b64_json": "AAAA"}]}

    Capture("k").image("p")
    w, h = (int(n) for n in sent["size"].split("x"))
    assert sent["size"] == hero_art_gen.IMAGE_SIZE and w > h


def test_no_summary_never_gives_the_vault_the_name_is_the_fallback_and_duplicate_themes_are_redone():
    fake = FakeProvider(theme="a holographic globe with flight arcs")
    theme, _cost, source = hero_art_gen.distill_theme(fake, "CorstoneSolbrook", "", "name")
    assert (theme, source) == ("a holographic globe with flight arcs", "name") and fake.calls == [("CorstoneSolbrook", "", "")]
    assert not hasattr(hero_art_prompt, "DEFAULT_THEMES")
    class Dead(FakeProvider):
        def distill(self, name, summary, avoid=""):
            raise hero_art_gen.ArtError("down")

    assert hero_art_gen.distill_theme(Dead(), "junstone-novwick", "", "name")[0] is None
    prompt = hero_art_prompt.build_prompt("project", None, "junstone-novwick")
    assert "junstone-novwick" in prompt and "vault" not in prompt.replace("safe, vault", "")
    items = {("project", 1): {"name": "A", "theme": "a vault", "source": "readme"},
             ("project", 2): {"name": "B", "theme": "A  Vault", "source": "readme"},
             ("project", 3): {"name": "C", "theme": "a lathe", "source": "readme"}}
    redo = FakeProvider(theme="a lighthouse")
    hero_art_gen.redistill_duplicates(redo, items)
    assert redo.calls == [("B", "", "a vault")] and items[("project", 2)]["theme"] == "a lighthouse"
    assert items[("project", 1)]["theme"] == "a vault" and items[("project", 3)]["source"] == "readme"
