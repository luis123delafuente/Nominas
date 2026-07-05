import os
import re

import pytest
from pypdf import PdfReader

from app.db import NIF_MEDIFORM_PLUS
from app.pdf_parser import SinNominasDetectadas, detectar_nominas, separar_pdf

DNI_NIE_PATTERN = re.compile(r"^(\d{8}[A-Z]|[XYZ]\d{7}[A-Z])$")

PDF_EJEMPLO = os.path.join(os.path.dirname(__file__), "..", "entrada", "NOMINAS_062026.pdf")

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
