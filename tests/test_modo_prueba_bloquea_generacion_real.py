import pytest

from app.config import Configuracion, GeneracionBloqueadaPorModoPrueba, asegurar_generacion_permitida


def test_modo_prueba_bloquea_la_generacion():
    config = Configuracion(modo_envio="prueba", email_prueba="prueba@example.com")

    with pytest.raises(GeneracionBloqueadaPorModoPrueba):
        asegurar_generacion_permitida(config, "fichero SEPA")


def test_modo_produccion_permite_la_generacion():
    config = Configuracion(modo_envio="produccion", email_prueba=None)

    asegurar_generacion_permitida(config, "fichero SEPA")  # no lanza nada


def _generador_de_fichero_real_ficticio(config: Configuracion, ruta) -> None:
    """Representa cualquier generador futuro (SEPA u otro) que escriba un fichero
    subible a un sistema externo: debe llamar a la comprobación ANTES de escribir nada."""
    asegurar_generacion_permitida(config, "fichero de prueba")
    ruta.write_text("contenido de un fichero real")


def test_en_modo_prueba_nunca_llega_a_existir_el_fichero(tmp_path):
    config = Configuracion(modo_envio="prueba", email_prueba="prueba@example.com")
    ruta = tmp_path / "fichero_real.xml"

    with pytest.raises(GeneracionBloqueadaPorModoPrueba):
        _generador_de_fichero_real_ficticio(config, ruta)

    assert not ruta.exists()  # bloqueado de forma verificable: ni siquiera se crea


def test_en_modo_produccion_el_fichero_se_genera(tmp_path):
    config = Configuracion(modo_envio="produccion", email_prueba=None)
    ruta = tmp_path / "fichero_real.xml"

    _generador_de_fichero_real_ficticio(config, ruta)

    assert ruta.exists()
