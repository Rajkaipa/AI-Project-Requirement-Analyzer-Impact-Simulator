# src/tools/file_parsers.py

from __future__ import annotations

import io
import os
from typing import Any, List

from google import genai
from google.genai import types

# Optional: PDF support
try:
    from PyPDF2 import PdfReader  # type: ignore
except ImportError:  # pragma: no cover
    PdfReader = None  # type: ignore


# --------------------------------------------------------------------
# Shared helpers
# --------------------------------------------------------------------


def _get_genai_client() -> genai.Client:
    """Create a Google GenAI client using the same env var as main_agent."""
    api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Missing GOOGLE_API_KEY (or GENAI_API_KEY). "
            "Set it in your environment to use file->text parsing."
        )
    return genai.Client(api_key=api_key)


# --------------------------------------------------------------------
# PDF parsing
# --------------------------------------------------------------------


def _extract_text_from_pdf_bytes(data: bytes) -> str:
    """Best-effort text extraction from a PDF byte stream."""
    if not PdfReader:
        return ""

    text_chunks: List[str] = []
    with io.BytesIO(data) as buf:
        try:
            reader = PdfReader(buf)
        except Exception:
            return ""

        for page in reader.pages:
            try:
                page_text = page.extract_text() or ""
            except Exception:
                page_text = ""
            if page_text.strip():
                text_chunks.append(page_text)

    return "\n".join(text_chunks).strip()


# --------------------------------------------------------------------
# Image (PNG/JPEG/WEBP) parsing via Gemini 2.0 Flash
# --------------------------------------------------------------------


def _extract_text_from_image_bytes(data: bytes, mime_type: str) -> str:
    """
    Use Gemini 2.0 Flash to read a whiteboard/screenshot and turn it into text.

    Returns plain text with both a transcription and cleaned requirements, e.g.:

    RAW_TEXT:
    (transcribed text)

    REQUIREMENTS:
    - ...
    - ...
    """
    client = _get_genai_client()

    image_part = types.Part.from_bytes(data=data, mime_type=mime_type)

    prompt = (
        "You are helping a project manager digitize a photo/screenshot of "
        "requirements (e.g., a whiteboard, sticky notes, sketch, etc.).\n\n"
        "1) Transcribe ALL readable text from the image as accurately as possible.\n"
        "2) Then rewrite that content as a clean list of software/project requirements.\n\n"
        "Respond in **plain text** only using this format:\n\n"
        "RAW_TEXT:\n"
        "<full transcription>\n\n"
        "REQUIREMENTS:\n"
        "- requirement 1\n"
        "- requirement 2\n"
        "- ...\n"
    )

    try:
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=[prompt, image_part],
        )
    except Exception:
        return ""

    return (response.text or "").strip()


# --------------------------------------------------------------------
# Main entrypoint: used by main_agent.py
# --------------------------------------------------------------------


def extract_text_from_files(uploaded_files: List[Any]) -> str:
    """
    Merge text extracted from a list of uploaded files.

    Supports:
    - .txt / .md / .json / .log / generic text
    - .pdf (via PyPDF2)
    - .png / .jpg / .jpeg / .webp (via Gemini 2.0 Flash OCR)

    Returns:
        A single string with section headers per file, which is then merged
        with the raw project input before analysis.
    """
    merged_chunks: List[str] = []

    for f in uploaded_files:
        if f is None:
            continue

        name = getattr(f, "name", "") or "uploaded_file"
        lower_name = name.lower()

        # Get raw bytes from Streamlit UploadedFile or generic file-like
        try:
            raw_bytes = f.getvalue()
        except Exception:
            try:
                raw_bytes = f.read()
            except Exception:
                raw_bytes = b""

        if not isinstance(raw_bytes, (bytes, bytearray)) or not raw_bytes:
            continue

        # PDF
        if lower_name.endswith(".pdf"):
            pdf_text = _extract_text_from_pdf_bytes(raw_bytes)
            if pdf_text:
                merged_chunks.append(
                    f"\n\n# Extracted from PDF file: {name}\n{pdf_text}"
                )
            continue

        # Images
        if lower_name.endswith((".png", ".jpg", ".jpeg", ".webp")):
            if lower_name.endswith(".png"):
                mime = "image/png"
            elif lower_name.endswith(".webp"):
                mime = "image/webp"
            else:
                mime = "image/jpeg"

            img_text = _extract_text_from_image_bytes(raw_bytes, mime)
            if img_text:
                merged_chunks.append(
                    f"\n\n# Extracted from image file: {name}\n{img_text}"
                )
            continue

        # Fallback: treat as text
        try:
            text = raw_bytes.decode("utf-8", errors="ignore")
        except Exception:
            text = ""

        if text.strip():
            merged_chunks.append(
                f"\n\n# Extracted from text file: {name}\n{text.strip()}"
            )

    return "\n\n".join(merged_chunks).strip()
