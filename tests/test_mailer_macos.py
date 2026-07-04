import pytest

from app.config import Configuracion
from app.mailer_macos import ConfiguracionInvalida, nota_modo_prueba, resolver_destinatario


def test_modo_prueba_redirige_siempre_al_email_de_prueba():
    config = Configuracion(modo_envio="prueba", email_prueba="pruebas@example.com")

    destinatario = resolver_destinatario("empleado.real@example.com", config)

    assert destinatario.email_envio == "pruebas@example.com"
    assert destinatario.email_produccion == "empleado.real@example.com"
    assert destinatario.es_modo_prueba is True


def test_modo_produccion_usa_el_email_real_del_empleado():
    config = Configuracion(modo_envio="produccion", email_prueba="pruebas@example.com")

    destinatario = resolver_destinatario("empleado.real@example.com", config)

    assert destinatario.email_envio == "empleado.real@example.com"
    assert destinatario.email_produccion is None
    assert destinatario.es_modo_prueba is False


def test_modo_prueba_sin_email_de_prueba_configurado_lanza_error_claro():
    config = Configuracion(modo_envio="prueba", email_prueba=None)

    with pytest.raises(ConfiguracionInvalida):
        resolver_destinatario("empleado.real@example.com", config)


def test_modo_prueba_ignora_por_completo_el_email_del_empleado():
    config = Configuracion(modo_envio="prueba", email_prueba="pruebas@example.com")

    for email_empleado in ["a@x.com", "otro@y.com", "cualquiera@z.com"]:
        destinatario = resolver_destinatario(email_empleado, config)
        assert destinatario.email_envio == "pruebas@example.com"


def test_nota_modo_prueba_visible_con_el_email_real():
    config = Configuracion(modo_envio="prueba", email_prueba="pruebas@example.com")
    destinatario = resolver_destinatario("empleado.real@example.com", config)

    nota = nota_modo_prueba(destinatario)

    assert nota is not None
    assert "empleado.real@example.com" in nota


def test_nota_modo_prueba_es_none_en_produccion():
    config = Configuracion(modo_envio="produccion", email_prueba="pruebas@example.com")
    destinatario = resolver_destinatario("empleado.real@example.com", config)

    assert nota_modo_prueba(destinatario) is None
