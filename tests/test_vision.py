"""Tests para agent.vision (bloques multimodales + marker PAGO_VERIFICADO)."""

import base64
import pytest

from agent.vision import (
    build_image_block,
    build_pdf_block,
    extract_pago_verificado,
    MAX_IMAGE_BYTES,
    MAX_PDF_BYTES,
)


def test_build_image_block_jpeg():
    block = build_image_block(b"FAKEJPG", "image/jpeg")
    assert block is not None
    assert block["type"] == "image_url"
    url = block["image_url"]["url"]
    assert url.startswith("data:image/jpeg;base64,")
    assert base64.b64decode(url.split(",", 1)[1]) == b"FAKEJPG"


def test_build_image_block_png():
    block = build_image_block(b"FAKEPNG", "image/png")
    assert block["image_url"]["url"].startswith("data:image/png;base64,")


def test_build_image_block_webp():
    block = build_image_block(b"x", "image/webp")
    assert block["image_url"]["url"].startswith("data:image/webp;base64,")


def test_build_image_block_mimetype_desconocido_fallback_jpeg():
    block = build_image_block(b"x", "image/heic")
    assert block["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_build_image_block_vacio_devuelve_none():
    assert build_image_block(b"", "image/jpeg") is None


def test_build_image_block_demasiado_grande_devuelve_none():
    huge = b"x" * (MAX_IMAGE_BYTES + 1)
    assert build_image_block(huge, "image/jpeg") is None


def test_build_pdf_block():
    block = build_pdf_block(b"%PDF-1.4 fake", "comprobante.pdf")
    assert block is not None
    assert block["type"] == "file"
    assert block["file"]["filename"] == "comprobante.pdf"
    assert block["file"]["file_data"].startswith("data:application/pdf;base64,")


def test_build_pdf_block_sin_nombre_usa_default():
    block = build_pdf_block(b"%PDF", "")
    assert block["file"]["filename"] == "document.pdf"


def test_build_pdf_block_vacio_devuelve_none():
    assert build_pdf_block(b"", "x.pdf") is None


def test_build_pdf_block_demasiado_grande_devuelve_none():
    huge = b"x" * (MAX_PDF_BYTES + 1)
    assert build_pdf_block(huge, "x.pdf") is None


# --- extract_pago_verificado ---

def test_extract_marker_al_final():
    text = "Recibido, todo OK. [PAGO_VERIFICADO]"
    clean, verified = extract_pago_verificado(text)
    assert verified is True
    assert clean == "Recibido, todo OK."


def test_extract_marker_al_principio():
    text = "[PAGO_VERIFICADO] Perfecto, registrado."
    clean, verified = extract_pago_verificado(text)
    assert verified is True
    assert clean == "Perfecto, registrado."


def test_extract_marker_solo():
    """Si el LLM solo emitió el marker sin texto adicional → verified, texto vacío."""
    clean, verified = extract_pago_verificado("[PAGO_VERIFICADO]")
    assert verified is True
    assert clean == ""


def test_extract_marker_case_insensitive():
    clean, verified = extract_pago_verificado("ok [pago_verificado]")
    assert verified is True
    assert clean == "ok"


def test_extract_marker_con_espacios_dentro():
    clean, verified = extract_pago_verificado("ok [ PAGO_VERIFICADO ]")
    assert verified is True
    assert clean == "ok"


def test_no_marker_devuelve_intacto():
    text = "Esta es una respuesta normal sin marker."
    clean, verified = extract_pago_verificado(text)
    assert verified is False
    assert clean == text


def test_extract_input_vacio():
    clean, verified = extract_pago_verificado("")
    assert verified is False
    assert clean == ""


def test_extract_normaliza_espacios_dobles():
    """Tras quitar el marker, no deben quedar dobles espacios."""
    text = "Recibido,  [PAGO_VERIFICADO]  todo bien."
    clean, verified = extract_pago_verificado(text)
    assert verified is True
    assert "  " not in clean
    assert "Recibido," in clean and "todo bien." in clean
