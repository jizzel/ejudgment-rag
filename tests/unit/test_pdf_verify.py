from pathlib import Path

import pytest

from ejudgment.domain.enums import VerificationStatus
from ejudgment.ingestion.pdf_verify import (
    PdfVerifier,
    char_grams,
    containment,
    contains_neutral_citation,
    sniff_mime_type,
    squash,
    tokens,
)
from tests.fixtures.legacy_fixture import make_docx, make_pdf

# Both texts share the standard heading, as real judgments do.
HEADING = "IN THE SUPERIOR COURT OF JUDICATURE\nIN THE SUPREME COURT OF GHANA\nACCRA"
TEXT = (
    f"{HEADING}\nKwame Mensah, appellant, against Ama Owusu, respondent.\n"
    "The tenancy agreement of 1998 was never registered with the Rent Control Department."
)
OTHER = (
    f"{HEADING}\nThe Republic against Kofi Boateng.\n"
    "The accused was charged with stealing four goats from the market at Ejura."
)


@pytest.fixture
def verifier(tmp_path: Path) -> PdfVerifier:
    return PdfVerifier(tmp_path, pages=2, min_window_chars=10000, min_overlap=0.8)


def _write(base: Path, name: str, text: str) -> str:
    (base / name).write_bytes(make_pdf(text.splitlines()))
    return name


def test_containment() -> None:
    assert containment(tokens("a bb ccc dddd"), tokens("ccc dddd eeee")) == 1.0
    assert containment(set(), {"x"}) == 0.0


def test_squash_and_char_grams() -> None:
    assert squash("In The  SUPERIOR-Court!") == "inthesuperiorcourt"
    assert char_grams("abcdef", 4) == {"abcd", "bcde", "cdef"}


def test_verified_when_legacy_text_lost_its_spaces(tmp_path: Path, verifier: PdfVerifier) -> None:
    name = _write(tmp_path, "a.pdf", TEXT)
    glued = TEXT.replace(" ", "")  # how the legacy extractor often rendered text
    check = verifier.verify(name, reference_text=glued, title=None, path_shared=False)
    assert check.status is VerificationStatus.VERIFIED


def test_verified_when_text_matches(tmp_path: Path, verifier: PdfVerifier) -> None:
    name = _write(tmp_path, "a.pdf", TEXT)
    check = verifier.verify(name, reference_text=TEXT, title=None, path_shared=False)
    assert check.status is VerificationStatus.VERIFIED
    assert check.sha256 is not None and len(check.sha256) == 64
    assert check.score == 1.0


def test_mismatch_when_file_belongs_to_another_judgment(
    tmp_path: Path, verifier: PdfVerifier
) -> None:
    name = _write(tmp_path, "shared.pdf", OTHER)
    check = verifier.verify(name, reference_text=TEXT, title=None, path_shared=True)
    assert check.status is VerificationStatus.MISMATCH
    assert check.reason == "text_mismatch"


def test_missing_file(verifier: PdfVerifier) -> None:
    check = verifier.verify("gone.pdf", reference_text=TEXT, title=None, path_shared=False)
    assert check.status is VerificationStatus.MISSING
    assert check.reason == "file_not_found"


def test_path_outside_base_dir_is_refused(verifier: PdfVerifier) -> None:
    check = verifier.verify("../../etc/passwd", reference_text=TEXT, title=None, path_shared=False)
    assert check.status is VerificationStatus.MISSING
    assert check.reason == "path_outside_base_dir"


def test_no_reference_text_falls_back_to_title(tmp_path: Path, verifier: PdfVerifier) -> None:
    name = _write(tmp_path, "scan.pdf", "Mensah Vrs Owusu\ncover page")
    check = verifier.verify(name, reference_text=None, title="Mensah Vrs Owusu", path_shared=False)
    assert check.status is VerificationStatus.VERIFIED
    assert check.reason == "title_match"


def test_unverifiable_unique_path_stays_unverified(tmp_path: Path, verifier: PdfVerifier) -> None:
    name = _write(tmp_path, "blank.pdf", "")
    check = verifier.verify(name, reference_text=None, title="Mensah Vrs Owusu", path_shared=False)
    assert check.status is VerificationStatus.UNVERIFIED


def test_unverifiable_shared_path_is_a_mismatch(tmp_path: Path, verifier: PdfVerifier) -> None:
    name = _write(tmp_path, "blank.pdf", "")
    check = verifier.verify(name, reference_text=None, title="Mensah Vrs Owusu", path_shared=True)
    assert check.status is VerificationStatus.MISMATCH
    assert check.reason == "shared_path_unverifiable"


def test_unreadable_pdf(tmp_path: Path, verifier: PdfVerifier) -> None:
    (tmp_path / "broken.pdf").write_bytes(b"%PDF-1.4\ntruncated garbage")
    check = verifier.verify("broken.pdf", reference_text=None, title=None, path_shared=False)
    assert check.status is VerificationStatus.UNVERIFIED
    assert check.reason == "unreadable_pdf"


def test_unknown_file_type_is_not_a_pdf(tmp_path: Path, verifier: PdfVerifier) -> None:
    (tmp_path / "junk.pdf").write_bytes(b"not a pdf at all")
    check = verifier.verify("junk.pdf", reference_text=None, title=None, path_shared=False)
    assert check.status is VerificationStatus.UNVERIFIED
    assert check.reason == "not_a_pdf"
    assert check.mime_type == "application/octet-stream"


def test_no_local_path() -> None:
    check = PdfVerifier(Path("."), pages=1, min_window_chars=1000, min_overlap=0.8).verify(
        None, reference_text=TEXT, title=None, path_shared=False
    )
    assert check.status is VerificationStatus.NOT_APPLICABLE


@pytest.mark.parametrize(
    ("content", "mime"),
    [
        (b"{\\rtf1\\ansi hello}", "application/rtf"),
        (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1rest", "application/msword"),
        (b"\n<!DOCTYPE html><html></html>", "text/html"),
        (b"PK\x03\x04not really a zip", "application/zip"),
        (b"random bytes", "application/octet-stream"),
    ],
)
def test_sniff_mime_type(tmp_path: Path, content: bytes, mime: str) -> None:
    path = tmp_path / "file.pdf"
    path.write_bytes(content)
    assert sniff_mime_type(path) == mime


def test_word_file_named_pdf_is_flagged(tmp_path: Path, verifier: PdfVerifier) -> None:
    make_docx(tmp_path / "judgment.pdf")
    check = verifier.verify("judgment.pdf", reference_text=None, title="X", path_shared=False)
    assert check.status is VerificationStatus.UNVERIFIED
    assert check.reason == "not_a_pdf"
    assert not check.is_pdf
    assert sniff_mime_type(tmp_path / "judgment.pdf").endswith("wordprocessingml.document")


def test_contains_neutral_citation() -> None:
    assert contains_neutral_citation("Cover\n[2020]  GHASC 104\n", "[2020] GHASC 104")
    assert contains_neutral_citation("2020 ghasc 104", "[2020] GHASC 104")
    assert not contains_neutral_citation("[2020] GHASC 1040", "[2020] GHASC 104")
    assert not contains_neutral_citation("[2020] GHASC 104", None)


def test_shared_path_with_only_party_names_is_a_mismatch(
    tmp_path: Path, verifier: PdfVerifier
) -> None:
    # Two decisions between the same parties collided on one truncated filename.
    name = _write(tmp_path, "shared.pdf", "Mensah Vrs Owusu\ncover page")
    check = verifier.verify(
        name,
        reference_text=None,
        title="Mensah Vrs Owusu",
        path_shared=True,
        neutral_citation="[2020] GHASC 105",
    )
    assert check.status is VerificationStatus.MISMATCH
    assert check.reason == "shared_path_title_only"


def test_shared_path_verified_by_own_citation(tmp_path: Path, verifier: PdfVerifier) -> None:
    name = _write(tmp_path, "shared.pdf", "Mensah Vrs Owusu\n[2020] GHASC 104\ncover page")
    owner = verifier.verify(
        name,
        reference_text=None,
        title="Mensah Vrs Owusu",
        path_shared=True,
        neutral_citation="[2020] GHASC 104",
    )
    other = verifier.verify(
        name,
        reference_text=None,
        title="Mensah Vrs Owusu",
        path_shared=True,
        neutral_citation="[2020] GHASC 105",
    )
    assert (owner.status, owner.reason) == (VerificationStatus.VERIFIED, "citation_match")
    assert other.status is VerificationStatus.MISMATCH
