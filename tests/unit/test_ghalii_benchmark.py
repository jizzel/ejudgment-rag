import csv
from datetime import date
from pathlib import Path

import pytest

from ejudgment.domain.schemas import SearchFilters
from ejudgment.evaluation import ghalii_benchmark as bench
from ejudgment.evaluation.retrieval import GoldQuestion
from ejudgment.worker.benchmark_ghalii import main

A = "/akn/gh/judgment/ghasc/2015/132/eng@2015-07-29"
A_COPY = "/akn/gh/judgment/ghasc/2015/140/eng@2015-07-29"
B = "/akn/gh/judgment/ghaca/2020/7/eng@2020-03-01"
COPIES = {
    A: [
        bench.CaseCopy(A, "X v Y [2015] GHASC 132"),
        bench.CaseCopy(A_COPY, "X v Y [2015] GHASC 140"),
    ],
    B: [bench.CaseCopy(B, "R v Z [2020] GHACA 7")],
}
QUESTIONS = [
    GoldQuestion(
        id="q-a", question="Who owns the land?", category="issue", gold_canonical_uris=[A]
    ),
    GoldQuestion(
        id="q-b",
        question="Appeal against sentence",
        category="fact_pattern",
        gold_canonical_uris=[B],
        filters=SearchFilters(court="ghaca", year_from=2019),
    ),
    GoldQuestion(
        id="q-none", question="Tax law of Mars", category="out_of_corpus", expect_no_answer=True
    ),
]


def _sheet(tmp_path: Path, rows: dict[str, dict[str, str]], repeat: tuple[str, ...] = ()) -> Path:
    path = tmp_path / "sheet.csv"
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=bench.SHEET_COLUMNS)
        writer.writeheader()
        for qid, values in [*rows.items(), *((r, rows[r]) for r in repeat)]:
            row = dict.fromkeys(bench.SHEET_COLUMNS, "")
            question = next((q for q in QUESTIONS if q.id == qid), None)
            row.update(id=qid, keyword_query=f"keywords for {qid}", searched_on="2026-10-13")
            if question:
                row.update(question=question.question, filters=bench.filters_json(question))
            row.update(values)
            writer.writerow(row)
    return path


FILLED = {
    # GhaLII links the re-publication, in work form: still the gold case.
    "q-a": {
        "verbatim_rank": "3",
        "verbatim_url": "https://ghalii.org/akn/gh/judgment/ghasc/2015/140/",
        "keywords_rank": "None",
        "keywords_url": "",
    },
    "q-b": {
        "verbatim_rank": "none",
        "keywords_rank": "12",
        "keywords_url": f"https://ghalii.org{B}?q=sentence",
    },
    "q-none": {"verbatim_result_count": "1,204", "keywords_result_count": "0"},
}


def test_a_complete_sheet_is_read(tmp_path: Path) -> None:
    rows = bench.read_recording_sheet(_sheet(tmp_path, FILLED), QUESTIONS, COPIES)
    got = {(r.question_id, r.arm): (r.rank, r.query, r.result_count) for r in rows}
    assert got == {
        ("q-a", "verbatim"): (3, "Who owns the land?", None),
        ("q-a", "keywords"): (None, "keywords for q-a", None),
        ("q-b", "verbatim"): (None, "Appeal against sentence", None),
        ("q-b", "keywords"): (12, "keywords for q-b", None),
        ("q-none", "verbatim"): (None, "Tax law of Mars", 1204),
        ("q-none", "keywords"): (None, "keywords for q-none", 0),
    }


@pytest.mark.parametrize(
    ("qid", "values", "message"),
    [
        ("q-a", {"verbatim_rank": ""}, "q-a verbatim: rank must be 1-20 or 'none'"),
        ("q-a", {"verbatim_rank": "21"}, "rank must be 1-20"),
        ("q-a", {"verbatim_url": ""}, "rank 3 needs the result's URL"),
        ("q-a", {"verbatim_url": f"https://ghalii.org{B}"}, "is not a gold case of this question"),
        (
            "q-a",
            {"verbatim_url": "https://ghalii.org/akn/gh/judgment/ghasc/2015/13"},
            "is not a gold case",
        ),
        ("q-b", {"verbatim_url": f"https://ghalii.org{B}"}, "rank 'none' but a URL was given"),
        ("q-none", {"verbatim_result_count": ""}, "q-none verbatim: record the result count"),
        ("q-none", {"keywords_result_count": "many"}, "is not a number"),
        ("q-none", {"verbatim_rank": "1"}, "no rank or URL for an out-of-corpus question"),
    ],
)
def test_recording_mistakes_are_reported(
    tmp_path: Path, qid: str, values: dict[str, str], message: str
) -> None:
    rows = {k: dict(v) for k, v in FILLED.items()}
    rows[qid].update(values)
    with pytest.raises(ValueError, match=message):
        bench.read_recording_sheet(_sheet(tmp_path, rows), QUESTIONS, COPIES)


def test_missing_and_unknown_questions_are_reported(tmp_path: Path) -> None:
    rows = {k: v for k, v in FILLED.items() if k != "q-b"} | {"q-zzz": {}}
    with pytest.raises(ValueError, match="q-zzz: not a gold question") as error:
        bench.read_recording_sheet(_sheet(tmp_path, rows), QUESTIONS, COPIES)
    assert "q-b: missing from the sheet" in str(error.value)


def test_mcnemar_exact() -> None:
    assert bench.mcnemar_p(0, 0) == 1.0
    assert bench.mcnemar_p(5, 0) == pytest.approx(2 / 32)
    assert bench.mcnemar_p(3, 3) == 1.0
    assert bench.mcnemar_p(1, 8) == pytest.approx(2 * 10 / 512)


def test_summary_pairs_the_systems_on_the_same_questions() -> None:
    def rec(qid: str, cat: str, ghalii: int | None, ours: int | None) -> dict[str, object]:
        return {
            "id": qid,
            "arm": "verbatim",
            "category": cat,
            "expect_no_answer": False,
            "ghalii_rank": ghalii,
            "ours_rank": ours,
        }

    records = [
        rec("1", "issue", None, 2),
        rec("2", "issue", 15, 1),
        rec("3", "citation", 1, 1),
        rec("4", "citation", None, None),
        {
            "id": "5",
            "arm": "verbatim",
            "category": "out_of_corpus",
            "expect_no_answer": True,
            "ghalii_rank": None,
            "ours_rank": None,
            "ghalii_result_count": 0,
        },
    ]
    out = bench.summarise(records)["verbatim"]
    assert out["answerable_questions"] == 4
    assert out["ghalii"] == {
        "recall@20": 0.5,
        "mrr@10": 0.25,
        "recall_by_category": {"citation": 0.5, "issue": 0.5},
    }
    assert out["ours"]["recall@20"] == 0.75
    assert out["ours"]["mrr@10"] == pytest.approx(round((0.5 + 1 + 1) / 4, 4))
    assert out["paired"] == {
        "both": 2,
        "only_ours": 1,
        "only_ghalii": 0,
        "neither": 1,
        "mcnemar_p": 1.0,
    }
    assert out["out_of_corpus"] == {"questions": 1, "ghalii_result_counts": {"5": 0}}
    assert "keywords" not in bench.summarise(records)


def test_recording_sheet_lists_every_copy_and_the_facets(tmp_path: Path) -> None:
    path = tmp_path / "sheet.csv"
    queries = {"q-a": "land ownership", "q-b": "sentence appeal", "q-none": "mars tax"}
    bench.write_recording_sheet(QUESTIONS, queries, COPIES, {"ghaca": "Court of Appeal"}, path)
    with path.open(newline="") as handle:
        rows = {r["id"]: r for r in csv.DictReader(handle)}
    assert rows["q-a"]["look_for"] == (
        f"X v Y [2015] GHASC 132 ({A}) | X v Y [2015] GHASC 140 ({A_COPY})"
    )
    assert rows["q-b"]["filters_to_apply"] == "Court: Court of Appeal; Years: 2019-any"
    assert rows["q-b"]["keyword_query"] == "sentence appeal"
    assert rows["q-none"]["look_for"].startswith("(outside the corpus")
    assert rows["q-a"]["verbatim_rank"] == ""


def test_query_sheet_hides_the_gold_cases(tmp_path: Path) -> None:
    gold = tmp_path / "gold.jsonl"
    gold.write_text("\n".join(q.model_dump_json() for q in QUESTIONS))
    out = tmp_path / "queries.csv"
    assert main(["--gold", str(gold), "queries", "--out", str(out)]) == 0
    content = out.read_text()
    assert "Who owns the land?" in content
    assert "akn" not in content and "GHASC" not in content
    with out.open(newline="") as handle:
        assert next(csv.DictReader(handle))["keyword_query"] == ""


def test_every_question_needs_a_keyword_query(tmp_path: Path) -> None:
    path = tmp_path / "queries.csv"
    bench.write_query_sheet(QUESTIONS, path)
    with pytest.raises(ValueError, match="q-a: no keyword query"):
        bench.read_keyword_queries(path, QUESTIONS)


def test_a_repeated_row_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="q-a: appears more than once"):
        bench.read_recording_sheet(_sheet(tmp_path, FILLED, repeat=("q-a",)), QUESTIONS, COPIES)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"question": "Who owns the house?"}, "q-a: question changed since the sheet was made"),
        ({"filters": '{"court": "ghasc"}'}, "q-a: filters changed since the sheet was made"),
        ({"filters": ""}, "q-a: filters changed"),
    ],
)
def test_a_sheet_for_an_older_question_is_rejected(
    tmp_path: Path, change: dict[str, str], message: str
) -> None:
    rows = {k: dict(v) for k, v in FILLED.items()}
    rows["q-a"].update(change)
    with pytest.raises(ValueError, match=message):
        bench.read_recording_sheet(_sheet(tmp_path, rows), QUESTIONS, COPIES)


def test_the_sheet_carries_the_filters_it_was_made_for(tmp_path: Path) -> None:
    path = tmp_path / "sheet.csv"
    queries = {q.id: "kw" for q in QUESTIONS}
    bench.write_recording_sheet(QUESTIONS, queries, COPIES, {}, path)
    with path.open(newline="") as handle:
        rows = {r["id"]: r for r in csv.DictReader(handle)}
    assert rows["q-b"]["filters"] == '{"court": "ghaca", "year_from": 2019}'
    assert rows["q-a"]["filters"] == "{}"


def test_sheets_are_written_into_new_directories(tmp_path: Path) -> None:
    queries = tmp_path / "evals" / "benchmarks" / "queries.csv"
    bench.write_query_sheet(QUESTIONS, queries)
    sheet = tmp_path / "other" / "sheet.csv"
    bench.write_recording_sheet(QUESTIONS, {q.id: "kw" for q in QUESTIONS}, COPIES, {}, sheet)
    assert queries.is_file() and sheet.is_file()


def _query_sheet(tmp_path: Path, change: dict[str, dict[str, str]]) -> Path:
    path = tmp_path / "queries.csv"
    bench.write_query_sheet(QUESTIONS, path)
    with path.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        row["keyword_query"] = f"kw {row['id']}"
        row.update(change.get(row["id"], {}))
    rows += [dict(rows[0]) for _ in change.get("repeat-first", {})]
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=bench.QUERY_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return path


def test_keyword_queries_are_read(tmp_path: Path) -> None:
    queries = bench.read_keyword_queries(_query_sheet(tmp_path, {}), QUESTIONS)
    assert queries == {"q-a": "kw q-a", "q-b": "kw q-b", "q-none": "kw q-none"}


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"q-a": {"question": "Who owns the house?"}}, "q-a: question changed since the sheet"),
        ({"q-b": {"filters": '{"court": "ghaca"}'}}, "q-b: filters changed since the sheet"),
        ({"repeat-first": {"x": ""}}, "q-a: appears more than once"),
        ({"q-a": {"id": "q-zzz"}}, "q-zzz: not a gold question"),
        ({"q-a": {"id": "q-zzz"}}, "q-a: missing from the sheet"),
    ],
)
def test_keyword_queries_for_another_question_are_rejected(
    tmp_path: Path, change: dict[str, dict[str, str]], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        bench.read_keyword_queries(_query_sheet(tmp_path, change), QUESTIONS)


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("", "q-a: searched_on must be a date \\(YYYY-MM-DD\\), got ''"),
        ("13/10/2026", "searched_on must be a date"),
        ("2026-13-01", "searched_on must be a date"),
        ("20261013", "searched_on must be a date"),
        ("2026-10-15", "q-a: searched_on 2026-10-15 is in the future"),
    ],
)
def test_every_row_needs_its_search_date(tmp_path: Path, value: str, message: str) -> None:
    rows = {k: dict(v) for k, v in FILLED.items()}
    rows["q-a"]["searched_on"] = value
    with pytest.raises(ValueError, match=message):
        bench.read_recording_sheet(
            _sheet(tmp_path, rows), QUESTIONS, COPIES, today=date(2026, 10, 14)
        )


def test_the_search_date_is_kept(tmp_path: Path) -> None:
    rows = bench.read_recording_sheet(
        _sheet(tmp_path, FILLED), QUESTIONS, COPIES, today=date(2026, 10, 13)
    )
    assert {r.searched_on for r in rows} == {"2026-10-13"}


def test_degraded_searches_are_listed() -> None:
    records = [
        {"id": "q-a", "arm": "verbatim", "ours_degraded": False, "ours_degraded_reason": None},
        {
            "id": "q-a",
            "arm": "keywords",
            "ours_degraded": True,
            "ours_degraded_reason": "reranker unavailable; results not reranked",
        },
        {"id": "q-b", "arm": "verbatim", "ours_degraded": True, "ours_degraded_reason": None},
    ]
    assert bench.degraded_searches(records) == [
        "q-a keywords: reranker unavailable; results not reranked",
        "q-b verbatim: degraded",
    ]
