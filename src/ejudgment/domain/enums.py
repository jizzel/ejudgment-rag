"""Closed vocabularies shared by the schema, ingestion and (later) the API."""

from enum import StrEnum


class RightsStatus(StrEnum):
    CC_BY_NC_LOCAL_EXPORT = "cc_by_nc_local_export"
    LICENSED = "licensed"
    UNKNOWN = "unknown"
    PROHIBITED = "prohibited"

    @property
    def eligible(self) -> bool:
        return self in (RightsStatus.CC_BY_NC_LOCAL_EXPORT, RightsStatus.LICENSED)


class EligibilityStatus(StrEnum):
    ELIGIBLE = "eligible"
    QUARANTINED = "quarantined"


class SourceStatus(StrEnum):
    TEXT_AVAILABLE = "text_available"
    OCR_PENDING = "ocr_pending"  # a PDF without machine-readable text
    CONVERSION_PENDING = "conversion_pending"  # a Word/RTF/HTML file saved as .pdf
    NO_SOURCE = "no_source"


class SourceKind(StrEnum):
    HTML = "html"
    PDF = "pdf"
    LEGACY = "legacy"


class VerificationStatus(StrEnum):
    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    MISMATCH = "mismatch"
    MISSING = "missing"
    NOT_APPLICABLE = "not_applicable"


class ExtractionMethod(StrEnum):
    PDF_TEXT = "pdf_text"  # machine-readable text from a PDF, page by page
    OCR = "ocr"  # Tesseract on rendered PDF pages, page by page
    CONVERTED = "converted"  # text converted from a Word file; no page mapping
    LEGACY = "legacy"  # text carried over from the legacy export; no page mapping


class QualityStatus(StrEnum):
    OK = "ok"
    NEEDS_REVIEW = "needs_review"


class PageReferenceStatus(StrEnum):
    VERIFIED = "verified"  # page bounds come from a verified PDF; usable for pinpoint cites
    UNKNOWN = "unknown"  # no page mapping (legacy or HTML text)
    PENDING = "pending"  # pages exist but the file is not verified yet


class IssueSeverity(StrEnum):
    QUARANTINE = "quarantine"
    WARNING = "warning"


class JobStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class LlmCallStatus(StrEnum):
    OK = "ok"
    ERROR = "error"


def check_in(column: str, enum: type[StrEnum]) -> str:
    """SQL CHECK expression restricting ``column`` to the enum's values."""
    values = ", ".join(f"'{member.value}'" for member in enum)
    return f"{column} IN ({values})"
