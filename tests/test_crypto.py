import fitz
from pypdf import PasswordType, PdfReader

from app.crypto import cifrar_pdf


def _crear_pdf_dummy(ruta: str, texto: str = "contenido de prueba") -> None:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), texto)
    doc.save(ruta)
    doc.close()


def test_pdf_cifrado_no_se_abre_con_password_incorrecta(tmp_path):
    origen = tmp_path / "original.pdf"
    destino = tmp_path / "cifrado.pdf"
    _crear_pdf_dummy(str(origen))

    cifrar_pdf(str(origen), str(destino), "02349419S")

    reader = PdfReader(str(destino))
    assert reader.is_encrypted
    assert reader.decrypt("clave-incorrecta") == PasswordType.NOT_DECRYPTED


def test_pdf_cifrado_se_abre_con_la_password_correcta_y_conserva_el_contenido(tmp_path):
    origen = tmp_path / "original.pdf"
    destino = tmp_path / "cifrado.pdf"
    _crear_pdf_dummy(str(origen), texto="ALCALDE LASAOSA, NICOLAS")

    cifrar_pdf(str(origen), str(destino), "02349419S")

    reader = PdfReader(str(destino))
    resultado = reader.decrypt("02349419S")

    assert resultado != PasswordType.NOT_DECRYPTED
    assert len(reader.pages) == 1
    assert "ALCALDE LASAOSA, NICOLAS" in reader.pages[0].extract_text()


def test_password_distingue_mayusculas(tmp_path):
    origen = tmp_path / "original.pdf"
    destino = tmp_path / "cifrado.pdf"
    _crear_pdf_dummy(str(origen))

    cifrar_pdf(str(origen), str(destino), "02349419S")

    reader = PdfReader(str(destino))
    assert reader.decrypt("02349419s") == PasswordType.NOT_DECRYPTED
