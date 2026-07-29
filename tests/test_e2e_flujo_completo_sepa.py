"""Prueba end-to-end de la Fase 3: recorre el flujo completo (subir PDF real -> detectar
y emparejar nóminas -> revisión con líquido autoextraído e IBAN -> generar fichero SEPA
-> validar el XML contra el esquema oficial) con los PDFs reales de las tres empresas
del cliente actual, incluyendo el caso real de un empleado que cobra de dos de ellas
el mismo mes.

No sustituye a los tests unitarios de fases anteriores (parser, matcher, cifrado,
validación IBAN/BIC, generador SEPA por separado): esos siguen probando cada pieza de
forma aislada. Esta prueba solo comprueba que, montadas todas juntas y con datos reales,
el resultado final es correcto — es la prueba que faltaba antes de desplegar.

Los IBAN de los empleados y de las cuentas de empresa son sintéticos (con dígito de
control válido, generados aquí mismo): no hay datos bancarios reales de prueba
disponibles, pero los nombres, DNIs, NIFs e importes sí son los reales de los PDFs de
la gestoría.
"""

import os
import re
import xml.etree.ElementTree as ET

import pytest
import xmlschema
from fastapi.testclient import TestClient

import app.main as main_module
from app.db import actualizar_iban_empleado, crear_cuenta_bancaria, crear_empleado, get_connection
from app.pdf_parser import detectar_nominas, extraer_mes_nomina

ENTRADA_DIR = os.path.join(os.path.dirname(__file__), "..", "entrada")
PDF_MEDIFORM = os.path.join(ENTRADA_DIR, "NOMINAS_062026.pdf")
PDF_FORMACION = os.path.join(ENTRADA_DIR, "Nom 0626-2.PDF")
PDF_NUESTRAFARMA = os.path.join(ENTRADA_DIR, "NUESTRAFARMA NOMINA_052026 v2.pdf")

XSD_PAIN_001 = os.path.join(os.path.dirname(__file__), "..", "schemas", "pain.001.001.03.xsd")

EMPRESAS = [
    {"nombre": "MEDIFORM PLUS S.L.", "nif": "B82827635", "pdf": PDF_MEDIFORM},
    {"nombre": "MEDIFORMPLUS FORMACION SL", "nif": "B88471149", "pdf": PDF_FORMACION},
    {"nombre": "NUESTRAFARMA PLUS SL", "nif": "B27523299", "pdf": PDF_NUESTRAFARMA},
]

# DNI real que aparece en los PDFs de MEDIFORM PLUS ("DE LA FUENTE RUIZ, LUIS") y de
# MEDIFORMPLUS FORMACION SL ("FUENTE RUIZ, LUIS FRANCISCO") con importes distintos —
# el caso real de una persona que cobra de dos empresas del cliente el mismo mes.
DNI_EMPLEADO_MULTIEMPRESA = "02855714B"

pytestmark = pytest.mark.skipif(
    not all(os.path.exists(p) for p in (PDF_MEDIFORM, PDF_FORMACION, PDF_NUESTRAFARMA)),
    reason="Requiere los tres PDFs reales de ejemplo en entrada/ (no versionados por ser datos sensibles)",
)

NS = {"p": "urn:iso:std:iso:20022:tech:xsd:pain.001.001.03"}


def _generar_iban_valido(indice: int) -> str:
    """IBAN español sintético con dígito de control ISO 7064 mod-97 correcto, para no
    depender de datos bancarios reales de prueba que no existen en el proyecto."""
    bban = f"{2100 + indice:04d}{0:08d}{1000 + indice:08d}"[:20]
    reordenado = bban + "ES00"
    convertido = "".join(str(int(c, 36)) for c in reordenado)
    digitos_control = 98 - (int(convertido) % 97)
    return f"ES{digitos_control:02d}{bban}"


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    """Monta una BD, clave de cifrado y config aisladas, con las tres empresas reales,
    sus cuentas bancarias, y un empleado (con IBAN) por cada DNI real distinto que
    aparece en los tres PDFs — incluido el empleado multiempresa, dado de alta UNA sola
    vez (una persona = una ficha), tal como exige el modelo de datos ya construido.
    """
    ruta_db = tmp_path / "test_nominas.db"
    ruta_clave = tmp_path / "clave_cifrado.key"
    monkeypatch.setattr(main_module, "get_connection", lambda db_path=ruta_db: get_connection(db_path))
    monkeypatch.setattr(main_module, "ENTRADA_DIR", tmp_path / "entrada")
    monkeypatch.setattr(main_module, "SALIDA_DIR", tmp_path / "salida")
    monkeypatch.setattr("app.crypto_campos.RUTA_CLAVE_POR_DEFECTO", ruta_clave)
    monkeypatch.setattr("app.config.RUTA_CONFIG_LOCAL", tmp_path / "config_no_existe.py")  # modo prueba por defecto

    conn = get_connection(ruta_db)

    empresas = {}
    for i, datos in enumerate(EMPRESAS):
        empresa_id = conn.execute(
            "INSERT INTO empresas (nombre, nif, activa) VALUES (?, ?, 1)", (datos["nombre"], datos["nif"])
        ).lastrowid
        conn.commit()
        cuenta_id = crear_cuenta_bancaria(
            conn,
            empresa_id,
            _generar_iban_valido(9000 + i),
            "BBVAESMMXXX",
            alias=f"Cuenta nómina {datos['nombre']}",
            ruta_clave=ruta_clave,
        )
        empresas[datos["nif"]] = {"id": empresa_id, "cuenta_id": cuenta_id, **datos}

    indice = 0
    ibans_por_dni = {}
    for datos in EMPRESAS:
        for nomina in detectar_nominas(datos["pdf"], datos["nif"]):
            if nomina.dni_nie in ibans_por_dni:
                continue  # el empleado multiempresa solo se da de alta una vez
            empleado_id = crear_empleado(
                conn, nomina.nombre_trabajador, nomina.dni_nie, f"empleado{indice}@example.com", "2025-01-01"
            )
            iban = _generar_iban_valido(indice)
            actualizar_iban_empleado(conn, empleado_id, iban, ruta_clave=ruta_clave)
            ibans_por_dni[nomina.dni_nie] = iban
            indice += 1
    conn.close()

    with TestClient(main_module.app) as client:
        yield client, empresas, tmp_path, ibans_por_dni


def _subir(client, empresa_id, ruta_pdf):
    with open(ruta_pdf, "rb") as f:
        return client.post(
            "/subir",
            files={"pdf": (os.path.basename(ruta_pdf), f, "application/pdf")},
            data={"empresa_id": empresa_id},
            follow_redirects=True,
        )


def _valores_liquido_del_html(html: str) -> dict:
    return {int(n): v for n, v in re.findall(r'name="sepa_liquido_(\d+)" value="([^"]*)"', html)}


def _numeros_incluibles_del_html(html: str) -> list:
    return [int(n) for n in re.findall(r'name="sepa_incluir" value="(\d+)"', html)]


def _generar_sepa_desde_pantalla_de_revision(client, cuenta_id, html_revisar):
    """Simula exactamente lo que hace el usuario: incluir todas las filas disponibles
    con el valor que ya ve prerrellenado en pantalla (autoextraído), sin escribir nada
    a mano — es el camino feliz que debe funcionar de punta a punta con datos reales."""
    numeros = _numeros_incluibles_del_html(html_revisar)
    valores = _valores_liquido_del_html(html_revisar)
    data = {"cuenta_id": str(cuenta_id), "sepa_incluir": [str(n) for n in numeros]}
    for n in numeros:
        data[f"sepa_liquido_{n}"] = valores[n]
    return client.post("/revisar/generar_sepa", data=data)


def _activar_modo_produccion(monkeypatch, tmp_path):
    ruta_config = tmp_path / "config.local.py"
    ruta_config.write_text('MODO_ENVIO = "produccion"\n')
    monkeypatch.setattr("app.config.RUTA_CONFIG_LOCAL", ruta_config)


def test_las_tres_empresas_generan_sepa_valido_de_forma_independiente_con_datos_reales(entorno, monkeypatch):
    client, empresas, tmp_path, _ = entorno
    _activar_modo_produccion(monkeypatch, tmp_path)
    esquema = xmlschema.XMLSchema(XSD_PAIN_001)

    for datos in EMPRESAS:
        empresa = empresas[datos["nif"]]
        nominas_reales = detectar_nominas(datos["pdf"], datos["nif"])
        mes_nomina = extraer_mes_nomina(datos["pdf"], nominas_reales[0].pagina_inicio)

        respuesta_subir = _subir(client, empresa["id"], datos["pdf"])
        assert respuesta_subir.status_code == 200
        assert "Autoextraído" in respuesta_subir.text  # el líquido se autoextrajo, no vacío
        assert "✓ Registrado" in respuesta_subir.text  # el IBAN del empleado se detecta

        respuesta_sepa = _generar_sepa_desde_pantalla_de_revision(
            client, empresa["cuenta_id"], respuesta_subir.text
        )
        assert respuesta_sepa.status_code == 200, (
            f"{datos['nombre']}: {respuesta_sepa.text[:300]}"
        )
        assert respuesta_sepa.headers["content-type"].startswith("application/xml")

        esquema.validate(respuesta_sepa.text)  # lanza si no es válido contra el XSD oficial

        raiz = ET.fromstring(respuesta_sepa.text)
        nb_of_txs = raiz.find(".//p:PmtInf/p:NbOfTxs", NS).text
        assert int(nb_of_txs) == len(nominas_reales), (
            f"{datos['nombre']}: se esperaban {len(nominas_reales)} transacciones, hay {nb_of_txs}"
        )

        ruta_salida = tmp_path / "salida" / datos["nif"] / mes_nomina / f"SEPA_{mes_nomina}.xml"
        assert ruta_salida.exists(), f"{datos['nombre']}: no se generó el fichero en {ruta_salida}"
        assert ruta_salida.read_text(encoding="utf-8") == respuesta_sepa.text


def test_empleado_multiempresa_no_mezcla_ni_duplica_pagos_entre_empresas(entorno, monkeypatch):
    client, empresas, tmp_path, ibans_por_dni = entorno
    _activar_modo_produccion(monkeypatch, tmp_path)

    empresa_mediform = empresas["B82827635"]
    empresa_formacion = empresas["B88471149"]

    respuesta_mediform = _subir(client, empresa_mediform["id"], PDF_MEDIFORM)
    xml_mediform = _generar_sepa_desde_pantalla_de_revision(
        client, empresa_mediform["cuenta_id"], respuesta_mediform.text
    ).text

    respuesta_formacion = _subir(client, empresa_formacion["id"], PDF_FORMACION)
    xml_formacion = _generar_sepa_desde_pantalla_de_revision(
        client, empresa_formacion["cuenta_id"], respuesta_formacion.text
    ).text

    iban_luis = ibans_por_dni[DNI_EMPLEADO_MULTIEMPRESA]

    for nombre_empresa, xml_texto, importe_esperado in [
        ("MEDIFORM PLUS S.L.", xml_mediform, "4604.06"),
        ("MEDIFORMPLUS FORMACION SL", xml_formacion, "2035.00"),
    ]:
        raiz = ET.fromstring(xml_texto)
        transacciones_de_luis = [
            tx
            for tx in raiz.findall(".//p:CdtTrfTxInf", NS)
            if tx.find("p:CdtrAcct/p:Id/p:IBAN", NS).text == iban_luis
        ]
        assert len(transacciones_de_luis) == 1, (
            f"{nombre_empresa}: se esperaba exactamente 1 pago a Luis, hay {len(transacciones_de_luis)}"
        )
        importe = transacciones_de_luis[0].find("p:Amt/p:InstdAmt", NS).text
        assert importe == importe_esperado, f"{nombre_empresa}: importe de Luis {importe}, esperado {importe_esperado}"

    # El fichero de una empresa nunca contiene ni un pago de más ni de menos por culpa
    # del otro: cada uno tiene exactamente el número de nóminas de SU PROPIO PDF.
    raiz_mediform = ET.fromstring(xml_mediform)
    raiz_formacion = ET.fromstring(xml_formacion)
    assert int(raiz_mediform.find(".//p:PmtInf/p:NbOfTxs", NS).text) == 29
    assert int(raiz_formacion.find(".//p:PmtInf/p:NbOfTxs", NS).text) == 4


def test_modo_prueba_bloquea_la_generacion_en_el_recorrido_completo_del_usuario(entorno):
    """A diferencia de test_sepa.py (que llama a generar_fichero_sepa() de forma
    aislada) y test_generar_sepa_endpoint.py (que ya prueba el endpoint con datos
    sintéticos), esto recorre el camino real: subir un PDF real, revisar, y solo
    entonces intentar generar — sin activar nunca el modo producción."""
    client, empresas, base_tmp_path, _ = entorno
    empresa = empresas["B27523299"]  # NUESTRAFARMA, la más pequeña (1 nómina) basta para probar el bloqueo

    respuesta_subir = _subir(client, empresa["id"], PDF_NUESTRAFARMA)
    assert respuesta_subir.status_code == 200
    assert "🧪 PRUEBA" in respuesta_subir.text  # el propio usuario ve que sigue en modo prueba

    respuesta_sepa = _generar_sepa_desde_pantalla_de_revision(client, empresa["cuenta_id"], respuesta_subir.text)

    assert respuesta_sepa.status_code == 400
    assert "produccion" in respuesta_sepa.text.lower()
    ruta_salida = base_tmp_path / "salida" / "B27523299" / "2026-05" / "SEPA_2026-05.xml"
    assert not ruta_salida.exists()
