import os
import re

import fitz
import pytest
from pypdf import PdfReader

from app.db import NIF_MEDIFORM_PLUS
from app.pdf_parser import (
    SinNominasDetectadas,
    _extraer_liquido_a_percibir,
    detectar_nominas,
    extraer_mes_nomina,
    separar_pdf,
)

DNI_NIE_PATTERN = re.compile(r"^(\d{8}[A-Z]|[XYZ]\d{7}[A-Z])$")

PDF_EJEMPLO = os.path.join(os.path.dirname(__file__), "..", "entrada", "NOMINAS_062026.pdf")
PDF_EJEMPLO_ESCANEADO = os.path.join(os.path.dirname(__file__), "..", "entrada", "7_NOMINAS_072026.pdf")
PDF_EJEMPLO_NUESTRAFARMA = os.path.join(
    os.path.dirname(__file__), "..", "entrada", "NUESTRAFARMA NOMINA_052026 v2.pdf"
)
PDF_EJEMPLO_FORMACION = os.path.join(os.path.dirname(__file__), "..", "entrada", "Nom 0626-2.PDF")
NIF_FORMACION = "B88471149"

pytestmark = pytest.mark.skipif(
    not os.path.exists(PDF_EJEMPLO),
    reason="Requiere el PDF de ejemplo real en entrada/NOMINAS_062026.pdf (no versionado por ser dato sensible)",
)


def test_detectar_nominas_cubre_todas_las_paginas_sin_solapes():
    nominas = detectar_nominas(PDF_EJEMPLO, NIF_MEDIFORM_PLUS)

    assert len(nominas) == 29
    for anterior, actual in zip(nominas, nominas[1:]):
        assert actual.pagina_inicio == anterior.pagina_fin + 1

    for nomina in nominas:
        assert nomina.nombre_trabajador.strip() != ""


def test_detectar_nominas_extrae_dni_con_formato_valido_en_todas():
    nominas = detectar_nominas(PDF_EJEMPLO, NIF_MEDIFORM_PLUS)

    for nomina in nominas:
        assert nomina.dni_nie is not None
        assert DNI_NIE_PATTERN.match(nomina.dni_nie)

    primera = nominas[0]
    assert primera.nombre_trabajador == "ALCALDE LASAOSA, NICOLAS"
    assert primera.dni_nie == "02349419S"


def test_separar_pdf_genera_un_pdf_de_una_pagina_por_nomina(tmp_path):
    rutas = separar_pdf(PDF_EJEMPLO, str(tmp_path), NIF_MEDIFORM_PLUS)

    assert len(rutas) == 29
    for ruta in rutas:
        assert len(PdfReader(ruta).pages) == 1


@pytest.mark.skipif(
    not os.path.exists(PDF_EJEMPLO_ESCANEADO),
    reason="Requiere '7_NOMINAS_072026.pdf' en entrada/ (no versionado por ser dato sensible)",
)
def test_detectar_nominas_pdf_escaneado_sin_capa_de_texto():
    """PDF escaneado (una imagen por página, sin capa de texto): el parser debe caer
    al OCR local de macOS Vision y detectar los mismos anclajes que con texto."""
    nominas = detectar_nominas(PDF_EJEMPLO_ESCANEADO, NIF_MEDIFORM_PLUS)

    assert len(nominas) == 29
    for anterior, actual in zip(nominas, nominas[1:]):
        assert actual.pagina_inicio == anterior.pagina_fin + 1

    for nomina in nominas:
        assert nomina.nombre_trabajador.strip() != ""
        # OCR no siempre lee bien un NIE (p.ej. 'Z' -> '2'): cuando el formato no es
        # reconocible el parser devuelve None y el matcher cae al emparejamiento por
        # nombre (con la contraseña correcta tomada de la ficha de la BD), nunca a un
        # DNI mal leído.
        assert nomina.dni_nie is None or DNI_NIE_PATTERN.match(nomina.dni_nie)

    primera = nominas[0]
    assert primera.nombre_trabajador == "ALCALDE LASAOSA, NICOLAS"
    assert primera.dni_nie == "02349419S"
    assert primera.liquido_a_percibir == "1.310,55"
    assert extraer_mes_nomina(PDF_EJEMPLO_ESCANEADO, primera.pagina_inicio) == "2026-07"


def test_detectar_nominas_con_nif_equivocado_informa_del_nif_real_detectado():
    with pytest.raises(SinNominasDetectadas) as excinfo:
        detectar_nominas(PDF_EJEMPLO, "Z99999999")

    assert excinfo.value.nif_esperado == "Z99999999"
    assert excinfo.value.nif_alternativo == NIF_MEDIFORM_PLUS


def test_extraer_mes_nomina_de_periodo_mens_junio():
    # "MENS 01 JUN 26 a 30 JUN 26" en la primera página del PDF de ejemplo.
    assert extraer_mes_nomina(PDF_EJEMPLO, 0) == "2026-06"


@pytest.mark.skipif(
    not os.path.exists(PDF_EJEMPLO_NUESTRAFARMA),
    reason="Requiere 'NUESTRAFARMA NOMINA_052026 v2.pdf' en entrada/ (no versionado por ser dato sensible)",
)
def test_extraer_mes_nomina_de_periodo_mens_mayo():
    # "MENS 15 MAY 26 a 31 MAY 26" en la primera página de este PDF de ejemplo.
    assert extraer_mes_nomina(PDF_EJEMPLO_NUESTRAFARMA, 0) == "2026-05"


def test_extraer_mes_nomina_devuelve_none_si_no_hay_cabecera_periodo(tmp_path):
    ruta = tmp_path / "sin_periodo.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Un PDF cualquiera sin la cabecera PERIODO.")
    doc.save(str(ruta))
    doc.close()

    assert extraer_mes_nomina(str(ruta), 0) is None


def test_extraer_mes_nomina_devuelve_none_si_pagina_fuera_de_rango():
    assert extraer_mes_nomina(PDF_EJEMPLO, 9999) is None


# --- Líquido a percibir: extracción exitosa por gestoría ya soportada -------------
#
# Las tres empresas del cliente comparten la misma gestoría (mismo anclaje "LIQUIDO A
# PERCIBIR" en las mismas coordenadas relativas), así que estos tres PDFs de ejemplo
# reales cubren la única gestoría soportada hoy, con datos y NIFs distintos cada uno.


def test_detectar_nominas_extrae_liquido_a_percibir_en_todas_mediform_plus():
    nominas = detectar_nominas(PDF_EJEMPLO, NIF_MEDIFORM_PLUS)

    for nomina in nominas:
        assert nomina.liquido_a_percibir is not None

    assert nominas[0].liquido_a_percibir == "1.572,84"  # ALCALDE LASAOSA, NICOLAS


@pytest.mark.skipif(
    not os.path.exists(PDF_EJEMPLO_NUESTRAFARMA),
    reason="Requiere 'NUESTRAFARMA NOMINA_052026 v2.pdf' en entrada/ (no versionado por ser dato sensible)",
)
def test_detectar_nominas_extrae_liquido_a_percibir_nuestrafarma():
    nominas = detectar_nominas(PDF_EJEMPLO_NUESTRAFARMA, "B27523299")

    assert len(nominas) == 1
    assert nominas[0].liquido_a_percibir == "1.980,47"


@pytest.mark.skipif(
    not os.path.exists(PDF_EJEMPLO_FORMACION),
    reason="Requiere 'Nom 0626-2.PDF' en entrada/ (no versionado por ser dato sensible)",
)
def test_detectar_nominas_extrae_liquido_a_percibir_formacion():
    nominas = detectar_nominas(PDF_EJEMPLO_FORMACION, NIF_FORMACION)

    assert len(nominas) > 0
    for nomina in nominas:
        assert nomina.liquido_a_percibir is not None


# --- Líquido a percibir: fallback silencioso al campo manual ----------------------


def test_extraer_liquido_a_percibir_devuelve_none_si_no_hay_cabecera(tmp_path):
    ruta = tmp_path / "sin_liquido.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((100, 100), "Un PDF cualquiera sin la cabecera esperada.")
    doc.save(str(ruta))
    doc.close()

    doc_leido = fitz.open(str(ruta))
    assert _extraer_liquido_a_percibir(doc_leido[0].get_text("words")) is None


def test_extraer_liquido_a_percibir_devuelve_none_si_no_hay_valor_debajo(tmp_path):
    ruta = tmp_path / "liquido_sin_valor.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((100, 100), "LIQUIDO A PERCIBIR")
    doc.save(str(ruta))
    doc.close()

    doc_leido = fitz.open(str(ruta))
    assert _extraer_liquido_a_percibir(doc_leido[0].get_text("words")) is None


def test_extraer_liquido_a_percibir_devuelve_none_si_el_valor_no_es_un_importe_valido(tmp_path):
    ruta = tmp_path / "liquido_invalido.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((100, 100), "LIQUIDO A PERCIBIR")
    page.insert_text((105, 115), "N/D")  # ni un importe ni un formato reconocible
    doc.save(str(ruta))
    doc.close()

    doc_leido = fitz.open(str(ruta))
    assert _extraer_liquido_a_percibir(doc_leido[0].get_text("words")) is None


def test_extraer_liquido_a_percibir_acepta_un_importe_valido_bajo_la_cabecera(tmp_path):
    ruta = tmp_path / "liquido_valido.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((100, 100), "LIQUIDO A PERCIBIR")
    page.insert_text((105, 115), "1.234,56")
    doc.save(str(ruta))
    doc.close()

    doc_leido = fitz.open(str(ruta))
    assert _extraer_liquido_a_percibir(doc_leido[0].get_text("words")) == "1.234,56"


def test_gestoria_sin_el_patron_de_liquido_no_bloquea_la_deteccion_de_nominas(tmp_path):
    """Requisito explícito: una gestoría sin el anclaje de líquido a percibir no debe
    romper ni bloquear el resto del parseo — solo cae a None (campo manual)."""
    ruta = tmp_path / "nomina_sin_liquido.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), "NIF. Z99999999")
    page.insert_text((72, 130), "TRABAJADOR/A")
    page.insert_text((300, 130), "CATEGORIA")
    page.insert_text((72, 145), "PERSONA, DE PRUEBA")
    page.insert_text((72, 160), "ANTIGUEDAD")
    page.insert_text((150, 160), "D.N.I.")
    page.insert_text((150, 175), "12345678A")
    page.insert_text((72, 500), "3. Cotización adicional horas extraordinarias")
    page.insert_text((72, 515), "4. Cotización adicional de solidaridad")
    doc.save(str(ruta))
    doc.close()

    nominas = detectar_nominas(str(ruta), "Z99999999")

    assert len(nominas) == 1
    assert nominas[0].liquido_a_percibir is None
    assert nominas[0].dni_nie == "12345678A"  # el resto del parseo no se ve afectado


@pytest.mark.parametrize("rotulo", ["C.I.F.", "CIF", "N.I.F.", "NIF:", "CIF :"])
def test_detectar_nominas_acepta_las_variantes_del_rotulo_del_cif(tmp_path, rotulo):
    """La gestoría no imprime siempre 'NIF.': el rótulo del anclaje de empresa puede
    aparecer como 'C.I.F.', 'CIF', 'N.I.F.', con ':' o '-' como separador. El parser
    debe aceptar todas las variantes con tal de que el CIF concreto sea el esperado."""
    ruta = tmp_path / "nomina_con_rotulo_variante.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), f"{rotulo} B82827635")
    page.insert_text((72, 130), "TRABAJADOR/A")
    page.insert_text((300, 130), "CATEGORIA")
    page.insert_text((72, 145), "PERSONA, DE PRUEBA")
    page.insert_text((72, 160), "ANTIGUEDAD")
    page.insert_text((150, 160), "D.N.I.")
    page.insert_text((150, 175), "12345678A")
    page.insert_text((72, 500), "3. Cotización adicional horas extraordinarias")
    page.insert_text((72, 515), "4. Cotización adicional de solidaridad")
    doc.save(str(ruta))
    doc.close()

    nominas = detectar_nominas(str(ruta), "B82827635")

    assert len(nominas) == 1
    assert nominas[0].nombre_trabajador == "PERSONA, DE PRUEBA"
    assert nominas[0].dni_nie == "12345678A"
