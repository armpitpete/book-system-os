from __future__ import annotations

import json

import pytest

from app.services import artifact_readiness as ar

S1, S2 = "1" * 64, "2" * 64
A1, A2 = "a" * 64, "b" * 64
C1, C2 = "c" * 64, "d" * 64
X1, X2 = "e" * 64, "f" * 64

REQ = {
    "schema_version": "1",
    "story_validation": {"profile_id": "story/full", "profile_version": "1"},
    "production_validation": {
        "production-valid": {"profile_id": "bos/base", "profile_version": "1"},
        "digital-publication-ready": {"profile_id": "bos/digital", "profile_version": "1"},
        "print-ready": {"profile_id": "bos/print", "profile_version": "1"},
    },
    "human_acceptance": {
        "digital-publication-ready": {"profile_id": "accept/digital", "profile_version": "1"},
        "print-ready": {"profile_id": "accept/print", "profile_version": "1"},
    },
}
CTX = {
    "schema_version": "1",
    "source_sha256": S1,
    "artifact_type": "pdf",
    "artifact_sha256": A1,
    "production_config_sha256": C1,
    "assets_sha256": X1,
}


def story(source=S1):
    return {
        "schema_version": "1", "profile_id": "story/full", "profile_version": "1",
        "source_sha256": source, "state": "pass",
        "decided_at": "2026-08-07T17:00:00Z", "evidence_id": "story-1",
    }


def prod(kind, artifact=A1, source=S1, config=C1, assets=X1):
    profile = {
        "production-valid": "bos/base",
        "digital-publication-ready": "bos/digital",
        "print-ready": "bos/print",
    }[kind]
    return {
        "schema_version": "1", "readiness_class": kind, "artifact_type": "pdf",
        "source_sha256": source, "artifact_sha256": artifact,
        "production_config_sha256": config, "assets_sha256": assets,
        "profile_id": profile, "profile_version": "1", "state": "pass",
        "evidence_id": f"prod-{kind}-{artifact[:1]}-{config[:1]}-{assets[:1]}",
    }


def accept(kind, artifact=A1):
    profile = {
        "digital-publication-ready": "accept/digital",
        "print-ready": "accept/print",
    }[kind]
    return {
        "schema_version": "1", "readiness_class": kind, "artifact_type": "pdf",
        "artifact_sha256": artifact, "profile_id": profile, "profile_version": "1",
        "state": "accepted", "decided_at": "2026-08-07T17:10:00Z",
        "evidence_id": f"accept-{kind}-{artifact[:1]}",
    }


def bundle(stories=None, productions=None, acceptances=None):
    return {
        "schema_version": "1",
        "story_validation": [story()] if stories is None else stories,
        "production_validation": [
            prod("production-valid"),
            prod("digital-publication-ready"),
            prod("print-ready"),
        ] if productions is None else productions,
        "human_acceptance": [
            accept("digital-publication-ready"),
            accept("print-ready"),
        ] if acceptances is None else acceptances,
    }


def states(evidence, context=None, requirements=None):
    return ar.evaluate_readiness(
        evidence,
        requirements=REQ if requirements is None else requirements,
        context=CTX if context is None else context,
    )["states"]


def test_exact_binding_passes_all_states():
    result = states(bundle())
    assert all(result[name]["ready"] for name in ar.READINESS_CLASSES)


def test_different_story_digest_fails_closed():
    result = states(bundle(stories=[story(S2)]))
    assert result["story-ready"]["reasons"] == ["story-validation-source-sha256-mismatch"]


def test_manuscript_change_after_story_validation_fails_closed():
    result = states(bundle(), {**CTX, "source_sha256": S2})
    assert result["story-ready"]["ready"] is False


def test_artifact_change_after_production_validation_fails_closed():
    result = states(bundle(), {**CTX, "artifact_sha256": A2})
    assert result["production-valid"]["reasons"] == [
        "production-validation-artifact-sha256-mismatch"
    ]


def test_regeneration_invalidates_human_acceptance():
    evidence = bundle(productions=[
        prod("production-valid", A2),
        prod("digital-publication-ready", A2),
        prod("print-ready", A2),
    ])
    result = states(evidence, {**CTX, "artifact_sha256": A2})
    assert result["production-valid"]["ready"] is True
    assert "human-acceptance-artifact-sha256-mismatch" in result[
        "digital-publication-ready"
    ]["reasons"]


def test_missing_story_validation_fails_closed():
    assert states(bundle(stories=[]))["story-ready"]["reasons"] == [
        "story-validation-missing"
    ]


def test_missing_production_validation_fails_closed():
    assert states(bundle(productions=[]))["production-valid"]["reasons"] == [
        "production-validation-missing"
    ]


def test_missing_human_acceptance_fails_closed():
    result = states(bundle(acceptances=[]))
    assert "human-acceptance-missing" in result["digital-publication-ready"]["reasons"]


def test_digital_does_not_imply_print():
    evidence = bundle(
        productions=[prod("production-valid"), prod("digital-publication-ready")],
        acceptances=[accept("digital-publication-ready")],
    )
    result = states(evidence)
    assert result["digital-publication-ready"]["ready"] is True
    assert result["print-ready"]["ready"] is False


def test_print_does_not_imply_digital():
    evidence = bundle(
        productions=[prod("production-valid"), prod("print-ready")],
        acceptances=[accept("print-ready")],
    )
    result = states(evidence)
    assert result["print-ready"]["ready"] is True
    assert result["digital-publication-ready"]["ready"] is False


def test_unknown_schema_and_profile_fail_closed():
    bad = bundle()
    bad["schema_version"] = "2"
    assert all(not x["ready"] for x in states(bad).values())

    mismatch = bundle(stories=[{**story(), "profile_id": "story/future"}])
    assert states(mismatch)["story-ready"]["reasons"] == [
        "story-validation-profile-mismatch"
    ]


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"production_config_sha256": C2}, "production-validation-config-sha256-mismatch"),
        ({"assets_sha256": X2}, "production-validation-assets-sha256-mismatch"),
    ],
)
def test_config_and_asset_changes_invalidate_production(change, reason):
    assert states(bundle(), {**CTX, **change})["production-valid"]["reasons"] == [reason]


def test_persisted_evidence_is_source_bound_and_tamper_evident(monkeypatch, tmp_path):
    monkeypatch.setattr(
        ar, "verify_job_source",
        lambda _: {"state": "available", "source_identity": {"source_sha256": S1}},
    )
    ar.persist_readiness_evidence(tmp_path, bundle())
    path = ar.readiness_evidence_path(tmp_path)
    assert ar.load_readiness_evidence(tmp_path)["schema_version"] == "1"

    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["evidence"]["story_validation"][0]["evidence_id"] = "tampered"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ar.ArtifactReadinessError) as exc:
        ar.load_readiness_evidence(tmp_path)
    assert exc.value.code == "readiness-evidence-integrity-mismatch"


def test_persistence_rejects_another_manuscript(monkeypatch, tmp_path):
    monkeypatch.setattr(
        ar, "verify_job_source",
        lambda _: {"state": "available", "source_identity": {"source_sha256": S1}},
    )
    with pytest.raises(ar.ArtifactReadinessError) as exc:
        ar.persist_readiness_evidence(tmp_path, bundle(stories=[story(S2)]))
    assert exc.value.code == "readiness-source-sha256-mismatch"


def test_v02_dry_run_never_claims_bos_readiness(monkeypatch):
    from app.services import publish_plan

    monkeypatch.setattr(publish_plan, "validate_manuscript", lambda **_: {"valid": True})
    result = publish_plan.build_publish_dry_run(title="Dry", markdown="# Dry\n")
    assert result["publishable"] is True
    assert result["readiness"]["evaluated"] is False
    assert all(not x["ready"] for x in result["readiness"]["states"].values())
    assert all(
        x["reasons"] == ["dry-run-structural-validation-only"]
        for x in result["readiness"]["states"].values()
    )


def test_conflicting_duplicate_evidence_fails_closed():
    duplicate = story()
    conflicting = {**duplicate, "state": "fail", "evidence_id": "story-conflict"}
    result = states(bundle(stories=[duplicate, conflicting]))
    assert all(not state["ready"] for state in result.values())
    assert all(
        state["reasons"] == ["readiness-evidence-invalid"]
        for state in result.values()
    )
