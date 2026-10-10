import asyncio
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, text

from ejudgment.api.main import create_app
from ejudgment.auth.service import create_user, login
from ejudgment.config import Settings
from ejudgment.domain.enums import UserRole
from ejudgment.evaluation import gold_review
from ejudgment.evaluation.answers import evaluate_answers
from ejudgment.evaluation.retrieval import EvalConfig, GoldQuestion, evaluate, load_gold
from ejudgment.generation.fake import FakeLLM
from ejudgment.ingestion.chunk_service import run_chunking
from ejudgment.ingestion.service import run_legacy_import
from ejudgment.ingestion.tokenizer import WhitespaceTokenizer
from ejudgment.verification.entailment import FakeNli
from tests.fixtures import legacy_fixture as fx
from tests.integration.test_chat import grounded

pytestmark = pytest.mark.integration

PASSWORD = "a long enough passphrase"
URI_37 = "/akn/gh/judgment/ghasc/2020/38/eng@2020-02-07"


@pytest.fixture
def secure(settings: Settings) -> Settings:
    return settings.model_copy(
        update={"auth_required": True, "auth_hash_secret": SecretStr("test-secret")}
    )


@pytest.fixture
def corpus(legacy_fixture: fx.LegacyFixture, secure: Settings, migrated_engine: Engine) -> Engine:
    run_legacy_import(
        legacy_fixture.db_path, legacy_fixture.base_dir, secure, engine=migrated_engine
    )
    run_chunking(migrated_engine, WhitespaceTokenizer(), secure)
    return migrated_engine


@pytest.fixture
def tokens(corpus: Engine, secure: Settings) -> dict[str, str]:
    result = {}
    with corpus.begin() as conn:
        for role in UserRole:
            email = f"{role.value}@example.org"
            create_user(
                conn,
                secure,
                email=email,
                display_name=f"{role.value.title()} User",
                password=PASSWORD,
                role=role,
            )
            result[role.value] = login(conn, secure, email, PASSWORD, client=None).token
    return result


@pytest.fixture
def client(corpus: Engine, secure: Settings) -> Iterator[TestClient]:
    app = create_app(secure, corpus, llm=FakeLLM(grounded), nli=FakeNli(), load_models=False)
    with TestClient(app) as test_client:
        yield test_client


def _as(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


DRAFT = {"question": "marker37x3", "category": "issue"}


def test_only_reviewers_and_admins_may_review(client: TestClient, tokens: dict[str, str]) -> None:
    assert client.get("/v1/review/questions").status_code == 401
    forbidden = client.get("/v1/review/questions", headers=_as(tokens["researcher"]))
    assert forbidden.status_code == 403 and forbidden.json()["error"]["code"] == "forbidden"
    for role in ("reviewer", "admin"):
        assert client.get("/v1/review/questions", headers=_as(tokens[role])).status_code == 200
    for role in UserRole:  # every role can see who they are (the UI shows the review link)
        me = client.get("/v1/auth/me", headers=_as(tokens[role.value]))
        assert me.status_code == 200 and me.json()["role"] == role.value
    created = client.post("/v1/review/questions", headers=_as(tokens["researcher"]), json=DRAFT)
    assert created.status_code == 403


def test_review_lifecycle_with_versions_and_history(
    client: TestClient, tokens: dict[str, str], corpus: Engine
) -> None:
    reviewer = _as(tokens["reviewer"])
    question_id = client.post("/v1/review/questions", headers=reviewer, json=DRAFT).json()["id"]
    assert question_id == "q-0001"

    def detail() -> Any:
        return client.get(f"/v1/review/questions/{question_id}", headers=reviewer).json()

    def act(action: str, version: int) -> Any:
        return client.post(
            f"/v1/review/questions/{question_id}/{action}",
            headers=reviewer,
            json={"version": version},
        )

    # Approval needs gold cases (or an expected abstention): refused first.
    refused = act("approve", 1)
    assert refused.status_code == 422 and refused.json()["error"]["code"] == "gold_invalid"
    labels = {
        **DRAFT,
        "gold_canonical_uris": [URI_37],
        "gold_passages": [
            {"canonical_uri": URI_37, "text": "marker37x3 marker37x4 marker37x5 marker37x6"}
        ],
        "version": 1,
    }
    assert (
        client.put(f"/v1/review/questions/{question_id}", headers=reviewer, json=labels).status_code
        == 204
    )
    stale = client.put(f"/v1/review/questions/{question_id}", headers=reviewer, json=labels)
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "version_conflict"
    assert act("approve", 2).status_code == 204
    approved = detail()["question"]
    assert approved["status"] == "approved" and approved["reviewed_by"] == "Reviewer User"
    # Editing an approved question sends it back to draft (it must be approved again).
    assert (
        client.put(
            f"/v1/review/questions/{question_id}", headers=reviewer, json={**labels, "version": 3}
        ).status_code
        == 204
    )
    assert detail()["question"]["status"] == "draft"
    assert act("retire", 4).status_code == 204
    assert act("approve", 5).status_code == 409  # a retired question can't be approved
    assert act("reopen", 5).status_code == 204
    history = [(h["action"], h["user"]) for h in detail()["history"]]
    assert history == [
        ("created", "Reviewer User"),
        ("edited", "Reviewer User"),
        ("approved", "Reviewer User"),
        ("edited", "Reviewer User"),
        ("retired", "Reviewer User"),
        ("reopened", "Reviewer User"),
    ]


def test_gold_passages_must_belong_to_gold_cases(
    client: TestClient, tokens: dict[str, str]
) -> None:
    reviewer = _as(tokens["reviewer"])
    question_id = client.post(
        "/v1/review/questions",
        headers=reviewer,
        json={
            **DRAFT,
            "gold_canonical_uris": [URI_37],
            "gold_passages": [
                {"canonical_uri": "/akn/gh/judgment/ghasc/2020/1/x", "text": "x" * 30}
            ],
        },
    ).json()["id"]
    refused = client.post(
        f"/v1/review/questions/{question_id}/approve", headers=reviewer, json={"version": 1}
    )
    assert refused.status_code == 422 and "not gold" in refused.json()["error"]["message"]


def test_candidates_use_the_question_filters(client: TestClient, tokens: dict[str, str]) -> None:
    reviewer = _as(tokens["reviewer"])
    question_id = client.post(
        "/v1/review/questions",
        headers=reviewer,
        json={**DRAFT, "filters": {"court": "ghasc", "year_from": 2020}},
    ).json()["id"]
    detail = client.get(f"/v1/review/questions/{question_id}", headers=reviewer).json()
    assert detail["candidates"]["query_info"]["filters_applied"] == {
        "court": "ghasc",
        "year_from": 2020,
    }
    assert detail["candidates"]["cases"][0]["judgment"]["canonical_uri"] == URI_37


def test_preview_answer_and_citation_lookup(
    client: TestClient, tokens: dict[str, str], corpus: Engine
) -> None:
    reviewer = _as(tokens["reviewer"])
    question_id = client.post("/v1/review/questions", headers=reviewer, json=DRAFT).json()["id"]
    preview = client.post(f"/v1/review/questions/{question_id}/preview-answer", headers=reviewer)
    assert preview.status_code == 200 and preview.json()["abstained"] is False
    with corpus.connect() as conn:
        audit = (
            conn.execute(text("SELECT endpoint FROM query_audit WHERE user_id IS NOT NULL"))
            .scalars()
            .all()
        )
    assert audit == ["/v1/review/preview-answer"]
    found = client.get(
        "/v1/review/judgments", headers=reviewer, params={"citation": "[2020] GHASC 38"}
    )
    assert found.json()["cases"][0]["judgment"]["citation"].startswith("Party37 Vrs Other37")


def test_import_is_idempotent_and_export_round_trips(
    corpus: Engine, tokens: dict[str, str], tmp_path: Any
) -> None:
    from ejudgment.config import REPO_ROOT

    seed = load_gold(REPO_ROOT / "evals" / "gold.jsonl")
    with corpus.begin() as conn:
        first = gold_review.import_questions(conn, seed)
        again = gold_review.import_questions(conn, seed)
        changed = gold_review.import_questions(
            conn, [seed[0].model_copy(update={"question": "something else"})]
        )
    assert (first.created, again.created, again.unchanged) == (len(seed), 0, len(seed))
    assert changed.differs == [seed[0].id]  # reported, not overwritten
    with corpus.begin() as conn:
        row = gold_review.get_question(conn, seed[0].id)
        gold_review.retire_question(conn, seed[0].id, row.version, None)
        path = tmp_path / "gold.jsonl"
        assert gold_review.export_jsonl(conn, path) == len(seed) - 1
    exported = load_gold(path)
    assert [q.id for q in exported] == sorted(q.id for q in seed[1:])  # retired one left out
    assert {q.id: q for q in exported} == {q.id: q for q in seed[1:]}  # content unchanged
    text_out = path.read_text()
    for secret in ("Reviewer User", "reviewer@example.org", "Admin User"):
        assert secret not in text_out


def test_evaluations_report_reviewed_questions_separately(corpus: Engine, secure: Settings) -> None:
    questions = [
        GoldQuestion(
            id="r",
            question="marker37x3",
            category="issue",
            gold_canonical_uris=[URI_37],
            reviewed=True,
            gold_passages=[{"canonical_uri": URI_37, "text": "marker37x3 marker37x4 marker37x5"}],
        ),
        GoldQuestion(
            id="u",
            question="marker38x3",
            category="issue",
            gold_canonical_uris=["/akn/gh/judgment/ghasc/2020/39/x"],
        ),
    ]
    metrics, _ = evaluate(
        corpus,
        secure,
        questions,
        embedder=None,
        reranker=None,
        configs=(EvalConfig("lexical", "lexical", False),),
        warmup=False,
    )
    reviewed = metrics["lexical"]["reviewed"]
    assert metrics["lexical"]["questions"] == 2 and reviewed["questions"] == 1
    assert reviewed["recall@20"] == 1.0 and reviewed["passage_recall@20"] == 1.0
    answer_metrics, _ = asyncio.run(
        evaluate_answers(
            corpus,
            secure,
            questions,
            embedder=None,
            reranker=None,
            llm=FakeLLM(grounded),
            nli=FakeNli(),
            run_id=uuid.uuid4(),
        )
    )
    assert answer_metrics["questions"] == 2 and answer_metrics["reviewed"]["questions"] == 1
    none_reviewed, _ = evaluate(
        corpus,
        secure,
        questions[1:],
        embedder=None,
        reranker=None,
        configs=(EvalConfig("lexical", "lexical", False),),
        warmup=False,
    )
    assert none_reviewed["lexical"]["reviewed"] is None


def test_export_refuses_incomplete_questions_and_keeps_the_file(
    corpus: Engine, tmp_path: Any, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    from ejudgment.config import REPO_ROOT
    from ejudgment.worker import gold as gold_worker

    seed = load_gold(REPO_ROOT / "evals" / "gold.jsonl")
    folder = tmp_path / "evals"
    folder.mkdir()
    path = folder / "gold.jsonl"
    with corpus.begin() as conn:
        gold_review.import_questions(conn, seed)
        gold_review.export_jsonl(conn, path)
    before = path.read_bytes()
    with corpus.begin() as conn:  # what "New question" in the UI creates: no labels yet
        new_id = gold_review.create_question(conn, gold_review.GoldDraft(**DRAFT), None)
    with corpus.connect() as conn, pytest.raises(gold_review.GoldExportError) as refused:
        gold_review.export_jsonl(conn, path)
    assert list(refused.value.problems) == [new_id]
    assert path.read_bytes() == before  # the evaluation file stays loadable
    assert sorted(p.name for p in folder.iterdir()) == ["gold.jsonl"]  # no temporary left
    # The CLI says so and fails, without touching the file.
    monkeypatch.setattr(gold_worker, "make_engine", lambda _settings: corpus)
    assert gold_worker.main(["export", "--file", str(path)]) == 1
    assert new_id in capsys.readouterr().err
    assert path.read_bytes() == before


def test_concurrent_creations_get_distinct_ids(corpus: Engine) -> None:
    import threading

    draft = gold_review.GoldDraft(**DRAFT)
    second: dict[str, Any] = {}

    def create_meanwhile() -> None:
        try:
            with corpus.begin() as conn:
                second["id"] = gold_review.create_question(conn, draft, None)
        except Exception as error:  # noqa: BLE001 - reported by the assertion below
            second["error"] = error

    with corpus.begin() as conn:
        first = gold_review.create_question(conn, draft, None)
        other = threading.Thread(target=create_meanwhile)
        other.start()
        other.join(timeout=1.0)  # still uncommitted here: the other creation must wait
        assert other.is_alive()
    other.join(timeout=10)
    assert "error" not in second, second.get("error")
    assert (first, second["id"]) == ("q-0001", "q-0002")


def test_export_that_would_not_load_leaves_the_file_alone(
    corpus: Engine, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The written file is loaded before it replaces the old one (a backstop beyond the
    per-question checks): a broken rendering never reaches the evaluation file."""
    from ejudgment.config import REPO_ROOT

    path = tmp_path / "gold.jsonl"
    path.write_text("previous\n")
    with corpus.begin() as conn:
        gold_review.import_questions(conn, load_gold(REPO_ROOT / "evals" / "gold.jsonl")[:2])
    monkeypatch.setattr(gold_review, "render_jsonl", lambda qs: '{"id": "broken"}\n')
    with corpus.connect() as conn, pytest.raises(ValueError):
        gold_review.export_jsonl(conn, path)
    assert path.read_text() == "previous\n"
    assert not (tmp_path / ".gold.jsonl.tmp").exists()


def test_detail_links_every_gold_case(
    client: TestClient, tokens: dict[str, str], corpus: Engine
) -> None:
    """Gold cases outside the current candidates still show their citation and GhaLII link;
    URIs that are not eligible judgments are left out (the UI marks them)."""
    with corpus.connect() as conn:
        quarantined = conn.execute(
            text("SELECT canonical_uri FROM judgments WHERE eligibility_status = 'quarantined'")
        ).scalar()
    assert quarantined
    missing = "/akn/gh/judgment/ghasc/1900/999/eng@1900-01-01"
    reviewer = _as(tokens["reviewer"])
    labels = {**DRAFT, "gold_canonical_uris": [missing, URI_37, quarantined]}
    question_id = client.post("/v1/review/questions", headers=reviewer, json=labels).json()["id"]
    detail = client.get(f"/v1/review/questions/{question_id}", headers=reviewer).json()
    assert [(c["canonical_uri"], c["source_url"]) for c in detail["gold_cases"]] == [
        (URI_37, f"https://ghalii.org{URI_37}")
    ]
    assert detail["gold_cases"][0]["citation"].startswith("Party37 Vrs Other37")
