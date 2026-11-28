
from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any, Dict

import pytest

from hosted.catalog_index.tools.index_builder import publishers as ib_publishers, releases as ib_releases
from hosted.catalog_index.tools.index_builder import review as ib_review, review_prompt as ib_review_prompt
from scripts.warez_gates import jobs, materialize as mat_mod, review as gate_review, static as gate_static
from scripts.warez_gates.gates import g02_schema, g03_kind_rules, g06_static, g07_secrets
from scripts.warez_gates.item import load_item
from scripts.warez_gates.models import ADVISORY, FAIL, PASS
from scripts.warez_gates.policy import load_policy
from src.core.catalog import minisign as client_minisign
from src.core.catalog.publish_github import build_hosted_github_payload, prepare_github_publish
from src.core.skills.digest import digest_directory
from src.plugins.host import identity
from src.plugins.sdk import cplug_validate
from tests.helpers import submissions_harness as sh
from tests.helpers.catalog_app import ledger_rows
from tests.helpers.minisign_keys import SKIP_REASON, minisign_binary
from tests.helpers.warez_slice5_e2e_fixtures import (
    CATALOG_SLUG,
    DARWIN_SANDBOX,
    REPO_ROOT,
    b64_members,
    build_12_gate_report,
    build_and_publish_checkout_index,
    create_signed_git_plugin_repo,
    make_runner_for_review_json,
    make_run_plugin_files,
    make_tier0_plugin_files,
    make_zip_bytes,
    open_e2e_bridge,
    publish_cplug_to_checkout,
    write_plugin_tree,
)


def _enable_local_file_git(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        mat_mod,
        "_GIT_HARDENING",
        ("-c", "protocol.allow=never", "-c", "protocol.file.allow=always", "-c", "core.hooksPath=/dev/null",
         "-c", "submodule.recurse=false", "-c", "transfer.fsckObjects=true"),
    )


def _preview_detail(resp) -> Dict[str, Any]:
    body = resp.json()
    return body["detail"] if isinstance(body.get("detail"), dict) else body


def _install_cplug_via_routes(
    ctx, item_id: str, *, acknowledge_flagged: bool = False, expect_flagged_409: bool = False
) -> Dict[str, Any]:
    preview = ctx.client.post("/api/v1/catalog/install/preview", json={"item_id": item_id, "scope": "global"})
    assert preview.status_code in (200, 409), preview.text
    sheet = _preview_detail(preview)
    consent: Dict[str, Any] = {
        "digest": sheet["digest"],
        "body_sha": sheet["body_sha"],
        "scripts": True,
        "cplug_accepted": True,
        "cplug_facts_sha": sheet["cplug_facts_sha"],
    }
    if acknowledge_flagged:
        consent["acknowledge_flagged"] = True
    resp = ctx.client.post(
        "/api/v1/catalog/install",
        json={"item_id": item_id, "scope": "global", "plan_token": sheet.get("plan_token"), "consent": consent},
    )
    if expect_flagged_409:
        assert resp.status_code == 409, resp.text
        detail = _preview_detail(resp)
        assert detail["code"] == "cplug_flagged_ack_required" and detail["flagged"] is True
        assert detail["requires_warning_ack"] is True and detail["warning_reasons"]
        return detail
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_e2e_github_pointer_and_upload_intake_with_unified_cplug_validate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    legacy_validator = REPO_ROOT / "hosted" / "catalog" / "api" / "validate_cplug.py"
    assert not legacy_validator.exists(), f"duplicate validator must stay deleted: {legacy_validator}"
    if minisign_binary() is None:
        pytest.skip(SKIP_REASON)

    files = make_run_plugin_files("gitintake", version="1.0.0")
    repo_bundle = create_signed_git_plugin_repo(
        tmp_path / "git_src", files=files, tag="v1.0.0", sign_ssh=True, sign_minisig=True
    )

    folder_dir = write_plugin_tree(tmp_path / "folder_pkg", files)
    kept_paths, v_errors = cplug_validate.validate_v2_folder_files(folder_dir)
    assert len(kept_paths) >= 3 and v_errors == []
    v2_manifest, _txt = cplug_validate.validate_cplug_members("gitintake", files, handle="harbor", version="1.0.0")
    assert v2_manifest.id == "gitintake"
    zip_raw = make_zip_bytes(files)
    (tmp_path / "pkg.zip").write_bytes(zip_raw)
    with zipfile.ZipFile(tmp_path / "pkg.zip", "r") as zf:
        zip_members = {name: zf.read(name) for name in zf.namelist()}
    assert cplug_validate.validate_cplug_members("gitintake", zip_members, handle="harbor", version="1.0.0")[0].id == "gitintake"

    with open_e2e_bridge(tmp_path) as ctx:
        api = ctx.api
        assert Path(api.validate_kinds.cplug_validate.__file__).resolve() == (
            REPO_ROOT / "src" / "plugins" / "sdk" / "cplug_validate.py"
        ).resolve()

        monkeypatch.setattr(
            api.github_intake, "_resolve_tag_sha",
            lambda slug, tag: repo_bundle.commit_sha if slug == "harbor/gitintake" and tag == "v1.0.0" else "",
        )
        prepared = prepare_github_publish(
            pointer="harbor/gitintake@v1.0.0", commit_sha=repo_bundle.commit_sha, kind="cplug", name="gitintake", version="1.0.0"
        )
        pure_resp = api.app.handler(
            sh.event("POST", "/v1/submissions", json.dumps(build_hosted_github_payload(prepared, is_v2=True)), ctx.submitter_token)
        )
        assert pure_resp["statusCode"] == 201, pure_resp["body"]
        pure_body = sh.body_of(pure_resp)
        sub_id = pure_body["submission_id"]
        assert pure_body["source_type"] == "github" and pure_body["git_commit_sha"] == repo_bundle.commit_sha

        before_calls = len(sh.storage_calls(api))
        bad_toml = json.dumps({
            "source_type": "upload", "kind": "cplug", "name": "badintake", "version": "1.0.0",
            "files": b64_members({"carnivore.toml": b"[broken\n"}),
        })
        assert api.app.handler(sh.event("POST", "/v1/submissions", bad_toml, ctx.submitter_token))["statusCode"] == 400
        bad_id = json.dumps({
            "source_type": "upload", "kind": "cplug", "name": "badintake", "version": "1.0.0",
            "files": b64_members({"carnivore.toml": b"schema = 2\nid = 'wrong_id'\n"}),
        })
        assert api.app.handler(sh.event("POST", "/v1/submissions", bad_id, ctx.submitter_token))["statusCode"] in (400, 409)
        assert len(sh.storage_calls(api)) == before_calls

        up_payload = json.dumps({
            "source_type": "upload", "kind": "cplug", "name": "zipintake", "version": "1.0.0",
            "files": b64_members(make_run_plugin_files("zipintake", version="1.0.0")),
        })
        up_resp = api.app.handler(sh.event("POST", "/v1/submissions", up_payload, ctx.submitter_token))
        assert up_resp["statusCode"] == 201 and sh.body_of(up_resp)["source_type"] == "upload"

        assert api.app.handler(
            sh.event("POST", f"/v1/submissions/{sub_id}/gate-claim", json.dumps({"owner": ctx.gate_adapter.owner}), ctx.gate_token)
        )["statusCode"] == 200

        _enable_local_file_git(monkeypatch)
        orig_clone = mat_mod._clone_github_tag
        monkeypatch.setattr(
            mat_mod, "_clone_github_tag", lambda _url, tag, dest: orig_clone(f"file://{repo_bundle.bare_dir}", tag, dest)
        )
        src_dir = tmp_path / "mat_src"
        src_dir.mkdir(parents=True)
        facts_doc = {
            "submission_id": sub_id, "kind": "cplug", "handle": "harbor", "name": "gitintake", "version": "1.0.0",
            "source_type": "github", "git_repo": "harbor/gitintake", "git_tag": "v1.0.0",
            "git_pointer": "harbor/gitintake@v1.0.0", "git_commit_sha": repo_bundle.commit_sha,
            "minisign_pubkey": repo_bundle.minisig_pub, "git_allowed_signers": repo_bundle.allowed_signers,
            "require_signed_provenance": True, "require_signed_tag": True,
        }
        (src_dir / "meta.json").write_text(json.dumps(facts_doc), encoding="utf-8")
        facts_file = tmp_path / "mat_facts.json"
        facts_file.write_text(json.dumps(facts_doc), encoding="utf-8")
        mat_out = tmp_path / "mat_out"
        assert mat_mod.materialize(src_dir, mat_out, facts_file=facts_file, api=ctx.gate_adapter, submission_id=sub_id) >= 3
        pinned_facts = json.loads(facts_file.read_text(encoding="utf-8"))
        assert pinned_facts["git_commit_sha"] == repo_bundle.commit_sha
        assert pinned_facts["provenance"]["signature_verified"] is True
        assert pinned_facts["folder_digest"] == digest_directory(mat_out)[0]
        stored_row = api.dynamodb.Table(api.submissions.SUBMISSIONS_TABLE).stored({"submission_id": sub_id})
        assert stored_row["folder_digest"] == pinned_facts["folder_digest"]
        assert stored_row["provenance"]["signature_verified"] is True


@pytest.mark.skipif(
    not DARWIN_SANDBOX or minisign_binary() is None,
    reason="Darwin sandbox-exec and minisign required for live Check 3 + Check 5 E2E",
)
def test_e2e_all_five_warez_checks_clean_run_and_tier0_autopublish(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    run_files = make_run_plugin_files("harborclock", version="1.0.0")
    tier0_files = make_tier0_plugin_files("tierzero", version="1.0.0")
    repo_run = create_signed_git_plugin_repo(
        tmp_path / "git_run",
        files=run_files,
        tag="v1.0.0",
        repo_slug="harbor/harborclock",
        embed_minisig_files=False,
    )

    with open_e2e_bridge(tmp_path) as ctx:
        api = ctx.api
        policy = load_policy()
        monkeypatch.setattr(api.github_intake, "_resolve_tag_sha", lambda _s, _t: repo_run.commit_sha)

        prep = prepare_github_publish(
            pointer="harbor/harborclock@v1.0.0", commit_sha=repo_run.commit_sha, kind="cplug", name="harborclock", version="1.0.0"
        )
        sub_resp = api.app.handler(
            sh.event("POST", "/v1/submissions", json.dumps(build_hosted_github_payload(prep, is_v2=True)), ctx.submitter_token)
        )
        assert sub_resp["statusCode"] == 201, sub_resp["body"]
        sub_id = sh.body_of(sub_resp)["submission_id"]
        assert api.app.handler(
            sh.event("POST", f"/v1/submissions/{sub_id}/gate-claim", json.dumps({"owner": ctx.gate_adapter.owner}), ctx.gate_token)
        )["statusCode"] == 200

        _enable_local_file_git(monkeypatch)
        orig_clone = mat_mod._clone_github_tag
        monkeypatch.setattr(
            mat_mod, "_clone_github_tag", lambda _u, tag, dest: orig_clone(f"file://{repo_run.bare_dir}", tag, dest)
        )
        mat_src = tmp_path / "run_mat_src"
        mat_src.mkdir()
        meta = {
            "submission_id": sub_id, "kind": "cplug", "handle": "harbor", "name": "harborclock", "version": "1.0.0",
            "source_type": "github", "git_repo": "harbor/harborclock", "git_tag": "v1.0.0",
            "git_pointer": "harbor/harborclock@v1.0.0", "git_commit_sha": repo_run.commit_sha,
            "minisign_pubkey": repo_run.minisig_pub, "provenance_sig": repo_run.provenance_sig,
            "git_allowed_signers": repo_run.allowed_signers,
        }
        (mat_src / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
        mat_out = tmp_path / "run_mat_out"
        mat_mod.materialize(mat_src, mat_out, api=ctx.gate_adapter, submission_id=sub_id)
        digest_run, _ = digest_directory(mat_out)
        facts_run = {**meta, "folder_digest": digest_run}
        item_run = load_item(mat_out, facts_run, policy, ctx.checkout)

        assert g02_schema.run(item_run).verdict == PASS
        assert g03_kind_rules.run(item_run).verdict == PASS
        static_results, _extra = gate_static.run_static(item_run)
        assert all(r.verdict in (PASS, ADVISORY) for r in static_results)

        fake_jwt = ".".join(["eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9", "eyJzdWIiOiIxMjM0NTY3ODkwIn0", "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"])
        evil_sec = write_plugin_tree(
            tmp_path / "evil_sec",
            {**make_run_plugin_files("evilsec"), "main.py": f'TOK = "{fake_jwt}"\n'.encode("utf-8")},
        )
        assert g07_secrets.run(load_item(evil_sec, {**facts_run, "name": "evilsec", "folder_digest": digest_directory(evil_sec)[0]}, policy, ctx.checkout)).verdict == FAIL

        evil_poly = write_plugin_tree(
            tmp_path / "evil_poly",
            {**make_run_plugin_files("evilpoly"), "main.py": "import subprocess\nu = 'https://p\u0430ypal.com'\nsubprocess.run('id', shell=True)\n".encode("utf-8")},
        )
        g6_bad = g06_static.run(load_item(evil_poly, {**facts_run, "name": "evilpoly", "folder_digest": digest_directory(evil_poly)[0]}, policy, ctx.checkout))
        assert g6_bad.verdict == FAIL and {"homoglyph_unicode", "shell_exec"} <= {f.code for f in g6_bad.findings}

        gate11_run = jobs.run_clean_room(item_run)
        assert (gate11_run.n, gate11_run.verdict, gate11_run.code) == (11, PASS, "ok")

        tier0_dir = write_plugin_tree(tmp_path / "tierzero_dir", tier0_files)
        tier0_item = load_item(
            tier0_dir,
            {"submission_id": "t" * 32, "kind": "cplug", "handle": "harbor", "name": "tierzero", "version": "1.0.0", "folder_digest": digest_directory(tier0_dir)[0]},
            policy, ctx.checkout,
        )
        assert all(r.verdict in (PASS, ADVISORY) for r in gate_static.run_static(tier0_item)[0])
        assert jobs.run_clean_room(tier0_item).verdict == PASS

        crash_dir = write_plugin_tree(tmp_path / "crash_dir", {**make_run_plugin_files("crashplug"), "main.py": b"import sys; sys.exit(7)\n"})
        crash_item = load_item(
            crash_dir,
            {"submission_id": "c" * 32, "kind": "cplug", "handle": "harbor", "name": "crashplug", "version": "1.0.0", "folder_digest": digest_directory(crash_dir)[0]},
            policy, ctx.checkout,
        )
        assert jobs.run_clean_room(crash_item).verdict == FAIL

        assert "cplug" in ib_review_prompt.KIND_CLAUSES
        for bad_sum in (
            "Only one sentence here.",
            "First sentence ok. Second sentence ok. Third sentence extra.",
            "Has bidi \u202e spoofing. Second sentence ok.",
            "# Heading injection\nSecond sentence ok.",
            "Has ```code block```. Second sentence ok.",
        ):
            with pytest.raises(ib_review.ReviewUnavailable):
                ib_review.validate_two_sentence_summary(bad_sum)

        norm_verdict, _, _ = ib_review.parse_review(json.dumps({
            "verdict": "clean",
            "summary": "This plugin reads input. It attempts credential theft.",
            "warnings": [{"kind": "credential_access", "detail": "reads secret env", "file": "main.py", "line": 1}],
        }))
        assert norm_verdict == "blocked"

        clean_model_json = json.dumps({
            "verdict": "clean",
            "summary": "Harbor Clock provides one read-only ping tool and a declarative widget. It runs inside the sandbox with no network or file permissions.",
            "warnings": [],
        })
        gate10_clean = gate_review.run(
            item_run, ctx.gate_adapter, "test-key",
            runner=make_runner_for_review_json(
                ctx.checkout, handle="harbor", name="harborclock", version="1.0.0", digest=digest_run, raw_model_json=clean_model_json
            ),
        )
        assert gate10_clean.verdict == PASS
        review_doc = item_run.notes["review"]

        report = build_12_gate_report(
            submission_id=sub_id, handle="harbor", name="harborclock", version="1.0.0", folder_digest=digest_run,
            static_results=static_results, gate10_verdict=gate10_clean.verdict, gate10_code=gate10_clean.code,
            gate10_findings=[], gate11_result=gate11_run, review_doc=review_doc, outcome="passed",
        )
        res_resp = api.app.handler(
            sh.event("POST", f"/v1/submissions/{sub_id}/gate-result", json.dumps({"owner": ctx.gate_adapter.owner, "outcome": "passed", "report": report}), ctx.gate_token)
        )
        assert res_resp["statusCode"] == 200 and sh.body_of(res_resp)["status"] == "approved"
        assert sh.body_of(res_resp)["auto_published"] is True
        rep_resp = api.app.handler(sh.event("GET", f"/v1/submissions/{sub_id}/report", bearer=ctx.submitter_token))
        assert rep_resp["statusCode"] == 200 and sh.body_of(rep_resp)["review"]["verdict"] == "clean"

        provenance_meta = {
            "source_type": "github", "repo": "harbor/harborclock", "tag": "v1.0.0",
            "commit_sha": repo_run.commit_sha, "signature_verified": True,
        }
        publish_cplug_to_checkout(
            ctx.checkout, tmp_path, handle="harbor", name="harborclock", version="1.0.0", files=run_files,
            publisher_kp=ctx.publisher_kp, served_root=ctx.served_root, provenance=provenance_meta, review=review_doc,
        )
        rel_path = ctx.checkout / "releases" / "harbor" / "harborclock" / "1.0.0.json"
        rel_doc = json.loads(rel_path.read_text(encoding="utf-8"))
        pub_key = client_minisign.parse_public_key(ctx.publisher_kp.public_key_text)
        sig_obj = client_minisign.Signature.from_index_fields(
            rel_doc["sig"]["key_id"], rel_doc["sig"]["sig"], rel_doc["sig"]["tc"], rel_doc["sig"]["gsig"]
        )
        assert client_minisign.verify(rel_doc["statement"].encode("utf-8"), sig_obj, pub_key, expect_prehashed=True)
        verified_rel = ib_releases.verify_release(
            ctx.checkout, rel_path, publishers=ib_publishers.load_publishers(ctx.checkout), repo_slug=CATALOG_SLUG
        )
        assert verified_rel.manifest_schema == 2 and verified_rel.provenance == provenance_meta

        build_and_publish_checkout_index(
            ctx.checkout, tmp_path, ctx.served_root, index_kp=ctx.index_kp, publisher_kp=ctx.publisher_kp,
            serial=2, reviews_by_key={("harbor/harborclock", "1.0.0"): review_doc},
        )
        assert ctx.client.post("/api/v1/catalog/refresh").status_code == 200
        assert _install_cplug_via_routes(ctx, "harbor/harborclock")["item_id"] == "harbor/harborclock"
        assert ledger_rows(ctx)[0].commit_sha == repo_run.commit_sha
        rec = identity.lookup(ctx.state, "harborclock")
        assert rec is not None and rec.commit_sha == repo_run.commit_sha


def test_e2e_autopublish_flagged_warning_ack_and_blocked_override_only(tmp_path: Path):
    if minisign_binary() is None:
        pytest.skip(SKIP_REASON)

    flagged_files = make_run_plugin_files(
        "flagplug", version="1.0.0", permissions={"network": [{"host": "api.example.com", "methods": ["GET"]}]}
    )
    flagged_files["main.py"] = (
        flagged_files["main.py"].decode("utf-8") + "\nimport urllib.request\n# https://api.example.com/status\n"
    ).encode("utf-8")

    with open_e2e_bridge(tmp_path) as ctx:
        api = ctx.api
        policy = load_policy()

        resp1 = api.app.handler(sh.event(
            "POST", "/v1/submissions",
            json.dumps({"source_type": "upload", "kind": "cplug", "name": "flagplug", "version": "1.0.0", "files": b64_members(flagged_files)}),
            ctx.submitter_token,
        ))
        assert resp1["statusCode"] == 201
        sub_flag = sh.body_of(resp1)["submission_id"]
        assert api.app.handler(
            sh.event("POST", f"/v1/submissions/{sub_flag}/gate-claim", json.dumps({"owner": ctx.gate_adapter.owner}), ctx.gate_token)
        )["statusCode"] == 200

        flag_dir = write_plugin_tree(tmp_path / "flag_dir", flagged_files)
        flag_digest, _ = digest_directory(flag_dir)
        flag_item = load_item(
            flag_dir, {"submission_id": sub_flag, "kind": "cplug", "handle": "harbor", "name": "flagplug", "version": "1.0.0", "folder_digest": flag_digest},
            policy, ctx.checkout,
        )
        static_res, _ = gate_static.run_static(flag_item)
        flagged_json = json.dumps({
            "verdict": "flagged",
            "summary": "Flag Plug queries api.example.com as declared in its permissions. Review the external host before enabling.",
            "warnings": [{"kind": "network", "detail": "queries external api.example.com", "file": "main.py", "line": 30}],
        })
        g10_flag = gate_review.run(
            flag_item, ctx.gate_adapter, "test-key",
            runner=make_runner_for_review_json(ctx.checkout, handle="harbor", name="flagplug", version="1.0.0", digest=flag_digest, raw_model_json=flagged_json),
        )
        assert g10_flag.verdict == ADVISORY
        flag_review = flag_item.notes["review"]
        flag_report = build_12_gate_report(
            submission_id=sub_flag, handle="harbor", name="flagplug", version="1.0.0", folder_digest=flag_digest,
            static_results=static_res, gate10_verdict=g10_flag.verdict, gate10_code=g10_flag.code,
            gate10_findings=[{"code": "review_network", "detector": "ai_review", "path": "main.py"}],
            gate11_result=jobs.GateResult(11, "clean_room", PASS, "ok", ()), review_doc=flag_review, outcome="passed_with_mentions",
        )
        gate_out = api.app.handler(sh.event(
            "POST", f"/v1/submissions/{sub_flag}/gate-result",
            json.dumps({"owner": ctx.gate_adapter.owner, "outcome": "passed_with_mentions", "report": flag_report}), ctx.gate_token,
        ))
        assert gate_out["statusCode"] == 200
        gate_body = sh.body_of(gate_out)
        assert gate_body["status"] == "approved" and gate_body["auto_published"] is True
        assert gate_body["flagged"] is True and gate_body["requires_warning_ack"] is True

        publish_cplug_to_checkout(
            ctx.checkout, tmp_path, handle="harbor", name="flagplug", version="1.0.0", files=flagged_files,
            publisher_kp=ctx.publisher_kp, served_root=ctx.served_root, review=flag_review,
        )
        build_and_publish_checkout_index(
            ctx.checkout, tmp_path, ctx.served_root, index_kp=ctx.index_kp, publisher_kp=ctx.publisher_kp,
            serial=2, reviews_by_key={("harbor/flagplug", "1.0.0"): flag_review},
        )
        assert ctx.client.post("/api/v1/catalog/refresh").status_code == 200
        _install_cplug_via_routes(ctx, "harbor/flagplug", acknowledge_flagged=False, expect_flagged_409=True)
        assert _install_cplug_via_routes(ctx, "harbor/flagplug", acknowledge_flagged=True)["item_id"] == "harbor/flagplug"

        blocked_files = make_run_plugin_files("blockplug", version="1.0.0")
        resp2 = api.app.handler(sh.event(
            "POST", "/v1/submissions",
            json.dumps({"source_type": "upload", "kind": "cplug", "name": "blockplug", "version": "1.0.0", "files": b64_members(blocked_files)}),
            ctx.submitter_token,
        ))
        assert resp2["statusCode"] == 201
        sub_blk = sh.body_of(resp2)["submission_id"]
        assert api.app.handler(
            sh.event("POST", f"/v1/submissions/{sub_blk}/gate-claim", json.dumps({"owner": ctx.gate_adapter.owner}), ctx.gate_token)
        )["statusCode"] == 200
        blk_digest = api.dynamodb.Table(api.submissions.SUBMISSIONS_TABLE).stored({"submission_id": sub_blk})["folder_digest"]
        blk_verdict, blk_summary, blk_warnings = ib_review.parse_review(json.dumps({
            "verdict": "blocked",
            "summary": "Block Plug attempts unauthorized environment credential harvesting. Do not publish without explicit security review.",
            "warnings": [{"kind": "credential_access", "detail": "reads secret tokens", "file": "main.py", "line": 1}],
        }))
        blk_review = {"status": "reviewed", "verdict": blk_verdict, "summary": blk_summary, "warnings": blk_warnings, "digest": blk_digest}
        blk_static = [jobs.GateResult(n, gid, PASS, "ok", ()) for n, gid in (
            (1, "structure"), (2, "schema"), (3, "kind_rules"), (4, "identity"), (5, "digest"),
            (6, "static_scans"), (7, "secrets"), (8, "license"), (9, "dependencies"),
        )]
        blk_report = build_12_gate_report(
            submission_id=sub_blk, handle="harbor", name="blockplug", version="1.0.0", folder_digest=blk_digest,
            static_results=blk_static, gate10_verdict=FAIL, gate10_code="review_blocked",
            gate10_findings=[{"code": "review_credential_access", "detector": "ai_review", "path": "main.py"}],
            gate11_result=jobs.GateResult(11, "clean_room", PASS, "ok", ()), review_doc=blk_review, outcome="blocked",
        )
        blk_res = api.app.handler(sh.event(
            "POST", f"/v1/submissions/{sub_blk}/gate-result",
            json.dumps({"owner": ctx.gate_adapter.owner, "outcome": "blocked", "report": blk_report, "overridable": True}), ctx.gate_token,
        ))
        assert blk_res["statusCode"] == 200
        blk_body = sh.body_of(blk_res)
        assert blk_body["status"] == "gate_failed" and blk_body["auto_published"] is False
        report_sha = blk_body["report_sha256"]

        assert api.app.handler(sh.event("POST", f"/v1/submissions/{sub_blk}/override", json.dumps({"reason": "nope", "report_sha256": report_sha}), ctx.submitter_token))["statusCode"] == 403
        bad_sha_ov = api.app.handler(sh.event("POST", f"/v1/submissions/{sub_blk}/override", json.dumps({"reason": "fp", "report_sha256": "0" * 64}), ctx.admin_token))
        assert bad_sha_ov["statusCode"] == 409 and sh.body_of(bad_sha_ov)["code"] == "report_mismatch"
        ok_ov = api.app.handler(sh.event("POST", f"/v1/submissions/{sub_blk}/override", json.dumps({"reason": "verified benign false positive", "report_sha256": report_sha}), ctx.admin_token))
        assert ok_ov["statusCode"] == 200 and sh.body_of(ok_ov)["status"] == "approved"


def test_e2e_one_click_instant_revoke_and_client_propagation(tmp_path: Path):
    if minisign_binary() is None:
        pytest.skip(SKIP_REASON)

    rev_files = make_run_plugin_files("revclock", version="1.0.0")
    with open_e2e_bridge(tmp_path) as ctx:
        api = ctx.api
        publish_cplug_to_checkout(
            ctx.checkout, tmp_path, handle="harbor", name="revclock", version="1.0.0",
            files=rev_files, publisher_kp=ctx.publisher_kp, served_root=ctx.served_root,
        )
        build_and_publish_checkout_index(
            ctx.checkout, tmp_path, ctx.served_root, index_kp=ctx.index_kp, publisher_kp=ctx.publisher_kp, serial=2
        )
        assert ctx.client.post("/api/v1/catalog/refresh").status_code == 200
        install_id = _install_cplug_via_routes(ctx, "harbor/revclock")["install_id"]

        sub_a, sub_b = "a" * 32, "b" * 32
        api.dynamodb.Table(api.submissions.SUBMISSIONS_TABLE).seed(
            {"submission_id": sub_a},
            {"status": "published", "item_id": "harbor/revclock", "handle": "harbor", "name": "revclock", "version": "1.0.0", "kind": "cplug", "created_at": "2026-11-26T00:00:00Z"},
        )
        api.dynamodb.Table(api.submissions.SUBMISSIONS_TABLE).seed(
            {"submission_id": sub_b},
            {"status": "published", "item_id": "harbor/otherplug", "handle": "harbor", "name": "otherplug", "version": "1.0.0", "kind": "cplug", "created_at": "2026-11-26T00:00:01Z"},
        )

        r_sub = api.app.handler(sh.event("POST", f"/v1/admin/submissions/{sub_a}/revoke", json.dumps({"reason": "security advisory"}), ctx.admin_token))
        assert r_sub["statusCode"] == 200 and sh.body_of(r_sub)["status"] == "revoked"
        r_item = api.app.handler(sh.event("POST", "/v1/admin/items/harbor/otherplug/revoke", json.dumps({"reason": "supply chain compromise"}), ctx.admin_token))
        assert r_item["statusCode"] == 200 and sub_b in sh.body_of(r_item)["submission_ids"]

        ctx.gate_adapter.claim_row(sub_a)
        assert ctx.gate_adapter.revocation_published(sub_a, merge_sha="1" * 40)["revocation_state"] == "published"

        build_and_publish_checkout_index(
            ctx.checkout, tmp_path, ctx.served_root, index_kp=ctx.index_kp, publisher_kp=ctx.publisher_kp,
            serial=3, revocations_list=[{"item": "harbor/revclock", "version": "1.0.0", "since": "2026-11-26T00:00:00Z"}],
        )
        ctx.clock.advance(15.0)
        ref = ctx.client.post("/api/v1/catalog/revocations/refresh")
        assert ref.status_code == 200 and ref.json()["serial"] == 3
        assert "harbor/revclock@1.0.0" in ref.json()["revoked_versions"]

        new_inst = ctx.client.post("/api/v1/catalog/install", json={"item_id": "harbor/revclock", "scope": "global"})
        assert new_inst.status_code == 409 and _preview_detail(new_inst)["code"] == "version_revoked"

        row_resp = ctx.client.get("/api/v1/cplugs/revclock")
        assert row_resp.status_code == 200
        row_json = row_resp.json()
        assert row_json["revoked"] is True and row_json["revocation_reason"] and row_json["revoked_since"]

        en_resp = ctx.client.put("/api/v1/cplugs/revclock", json={"revision": row_json["revision"], "enabled": True})
        assert en_resp.status_code == 409 and _preview_detail(en_resp)["code"] == "version_revoked"

        dis_resp = ctx.client.put("/api/v1/cplugs/revclock", json={"revision": row_json["revision"], "enabled": False})
        assert dis_resp.status_code == 200 and dis_resp.json()["enabled"] is False
        assert ctx.client.delete(f"/api/v1/catalog/installed/{install_id}").status_code == 200
        assert ledger_rows(ctx) == []


def test_e2e_preswap_permission_diff_rug_pull_guard(tmp_path: Path):
    if minisign_binary() is None:
        pytest.skip(SKIP_REASON)

    v1_files = make_tier0_plugin_files("rugplug", version="1.0.0", permissions={"read": ["sessions"], "reasons": {"sessions": "Read sessions"}})
    v2_widened_files = make_run_plugin_files(
        "rugplug", version="2.0.0",
        permissions={
            "read": ["sessions", "output"], "write": ["notify"],
            "network": [{"host": "api.example.com", "methods": ["GET"]}], "secrets": ["api_key"],
            "reasons": {"sessions": "Read sessions", "output": "Read session output", "notify": "Send notifications"},
        },
        services={"provides": [{"name": "rug.svc", "methods": ["ping"]}], "consumes": ["clock.svc"]},
        events={"on": ["session.created"], "emit": ["rug.ready"]},
    )
    v2_narrowed_files = make_run_plugin_files("rugplug", version="2.0.1", permissions={"read": ["sessions"], "reasons": {"sessions": "Read sessions"}})
    v2_cmd_changed_files = make_run_plugin_files(
        "rugplug", version="2.0.2", run_cmd=("python3", "alt_main.py"),
        permissions={"read": ["sessions"], "reasons": {"sessions": "Read sessions"}},
        extra_files={"alt_main.py": v2_narrowed_files["main.py"]},
    )

    with open_e2e_bridge(tmp_path) as ctx:
        c_v1, _d1, _ = publish_cplug_to_checkout(
            ctx.checkout, tmp_path, handle="harbor", name="rugplug", version="1.0.0", files=v1_files,
            publisher_kp=ctx.publisher_kp, served_root=ctx.served_root,
            provenance={"source_type": "github", "repo": "harbor/rugplug", "tag": "v1.0.0", "commit_sha": "1" * 40, "signature_verified": True},
        )
        build_and_publish_checkout_index(ctx.checkout, tmp_path, ctx.served_root, index_kp=ctx.index_kp, publisher_kp=ctx.publisher_kp, serial=2)
        assert ctx.client.post("/api/v1/catalog/refresh").status_code == 200
        install_id = _install_cplug_via_routes(ctx, "harbor/rugplug")["install_id"]
        installed_dir = ctx.state / "plugins" / "rugplug"
        assert (installed_dir / "carnivore.toml").is_file() and not (installed_dir / "main.py").exists()

        v1_retag_files = make_tier0_plugin_files("rugplug", version="1.0.1", permissions={"read": ["sessions"], "reasons": {"sessions": "Read sessions"}})
        publish_cplug_to_checkout(
            ctx.checkout, tmp_path, handle="harbor", name="rugplug", version="1.0.1", files=v1_retag_files,
            publisher_kp=ctx.publisher_kp, served_root=ctx.served_root,
            provenance={"source_type": "github", "repo": "harbor/rugplug", "tag": "v1.0.0", "commit_sha": "9" * 40, "signature_verified": True},
        )
        build_and_publish_checkout_index(ctx.checkout, tmp_path, ctx.served_root, index_kp=ctx.index_kp, publisher_kp=ctx.publisher_kp, serial=3)
        ctx.clock.advance(301.0)
        assert ctx.client.post("/api/v1/catalog/refresh").status_code == 200
        rev_now = ledger_rows(ctx)[0].revision
        sha_resp = ctx.client.post(f"/api/v1/catalog/installed/{install_id}/update", json={"expected_revision": rev_now})
        assert sha_resp.status_code == 409 and _preview_detail(sha_resp)["code"] == "commit_sha_mismatch"
        assert not (installed_dir / "main.py").exists()

        publish_cplug_to_checkout(
            ctx.checkout, tmp_path, handle="harbor", name="rugplug", version="2.0.0", files=v2_widened_files,
            publisher_kp=ctx.publisher_kp, served_root=ctx.served_root,
            provenance={"source_type": "github", "repo": "harbor/rugplug", "tag": "v2.0.0", "commit_sha": "2" * 40, "signature_verified": True},
        )
        build_and_publish_checkout_index(ctx.checkout, tmp_path, ctx.served_root, index_kp=ctx.index_kp, publisher_kp=ctx.publisher_kp, serial=4)
        ctx.clock.advance(301.0)
        assert ctx.client.post("/api/v1/catalog/refresh").status_code == 200

        rev_now = ledger_rows(ctx)[0].revision
        blocked_upd = ctx.client.post(f"/api/v1/catalog/installed/{install_id}/update", json={"expected_revision": rev_now})
        assert blocked_upd.status_code == 409
        blk_detail = _preview_detail(blocked_upd)
        assert blk_detail["code"] == "consent_required"
        pdiff = blk_detail["permission_diff"]
        assert pdiff["requires_reconsent"] is True
        assert "sessions.output" in pdiff["added"]["read"] and "notify" in pdiff["added"]["write"]
        assert "api.example.com" in pdiff["added"]["network"] and "api_key" in pdiff["added"]["secrets"]
        assert "rug.svc" in pdiff["added"]["services_provides"] and "clock.svc" in pdiff["added"]["services_consumes"]
        assert "session.created" in pdiff["added"]["events_on"] and "rug.ready" in pdiff["added"]["events_emit"]
        assert pdiff["execution_escalation"]["tier0_to_run"] is True
        assert (installed_dir / "carnivore.toml").is_file() and not (installed_dir / "main.py").exists()

        ok_upd = ctx.client.post(
            f"/api/v1/catalog/installed/{install_id}/update",
            json={
                "expected_revision": rev_now,
                "consent": {
                    "digest": blk_detail["digest"], "body_sha": blk_detail["body_sha"], "scripts": True,
                    "cplug_accepted": True, "cplug_facts_sha": blk_detail["cplug_facts_sha"], "accept_permission_escalation": True,
                },
            },
        )
        assert ok_upd.status_code == 200 and ok_upd.json()["version"] == "2.0.0"
        assert (installed_dir / "main.py").is_file() and ledger_rows(ctx)[0].commit_sha == "2" * 40

        publish_cplug_to_checkout(
            ctx.checkout, tmp_path, handle="harbor", name="rugplug", version="2.0.1", files=v2_narrowed_files,
            publisher_kp=ctx.publisher_kp, served_root=ctx.served_root,
            provenance={"source_type": "github", "repo": "harbor/rugplug", "tag": "v2.0.1", "commit_sha": "3" * 40, "signature_verified": True},
        )
        build_and_publish_checkout_index(ctx.checkout, tmp_path, ctx.served_root, index_kp=ctx.index_kp, publisher_kp=ctx.publisher_kp, serial=5)
        ctx.clock.advance(301.0)
        assert ctx.client.post("/api/v1/catalog/refresh").status_code == 200
        rev_now = ledger_rows(ctx)[0].revision
        narrow_probe = ctx.client.post(f"/api/v1/catalog/installed/{install_id}/update", json={"expected_revision": rev_now})
        if narrow_probe.status_code == 409:
            nd = _preview_detail(narrow_probe)
            assert nd["permission_diff"]["requires_reconsent"] is False
            narrow_ok = ctx.client.post(
                f"/api/v1/catalog/installed/{install_id}/update",
                json={
                    "expected_revision": rev_now,
                    "consent": {
                        "digest": nd["digest"], "body_sha": nd["body_sha"], "scripts": True,
                        "cplug_accepted": True, "cplug_facts_sha": nd["cplug_facts_sha"], "accept_permission_escalation": False,
                    },
                },
            )
            assert narrow_ok.status_code == 200, narrow_ok.text
        else:
            assert narrow_probe.status_code == 200

        publish_cplug_to_checkout(
            ctx.checkout, tmp_path, handle="harbor", name="rugplug", version="2.0.2", files=v2_cmd_changed_files,
            publisher_kp=ctx.publisher_kp, served_root=ctx.served_root,
            provenance={"source_type": "github", "repo": "harbor/rugplug", "tag": "v2.0.2", "commit_sha": "4" * 40, "signature_verified": True},
        )
        build_and_publish_checkout_index(ctx.checkout, tmp_path, ctx.served_root, index_kp=ctx.index_kp, publisher_kp=ctx.publisher_kp, serial=6)
        ctx.clock.advance(301.0)
        assert ctx.client.post("/api/v1/catalog/refresh").status_code == 200
        rev_now = ledger_rows(ctx)[0].revision
        cmd_upd = ctx.client.post(f"/api/v1/catalog/installed/{install_id}/update", json={"expected_revision": rev_now})
        assert cmd_upd.status_code == 409
        cmd_detail = _preview_detail(cmd_upd)
        assert cmd_detail["code"] == "consent_required" and cmd_detail["permission_diff"]["execution_escalation"]["run_cmd_changed"] is True
        assert json.loads((installed_dir / "carnivore.json").read_text(encoding="utf-8"))["version"] == "2.0.1"
