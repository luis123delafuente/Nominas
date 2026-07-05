import os
import re

import fitz
import pytest
from pypdf import PdfReader

from app.db import NIF_MEDIFORM_PLUS
from app.pdf_parser import SinNominasDetectadas, detectar_nominas, extraer_mes_nomina, separar_pdf

DNI_NIE_PATTERN = re.compile(r"^(\d{8}[A-Z]|[XYZ]\d{7}[A-Z])$")

PDF_EJEMPLO = os.path.join(os.path.dirname(__file__), "..", "entrada", "NOMINAS_062026.pdf")
PDF_EJEMPLO_NUESTRAFARMA = os.path.join(
    os.path.dirname(__file__), "..", "entrada", "NUESTRAFARMA NOMINA_052026 v2.pdf"
)

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
