import pytest

from app.validaciones_bancarias import normalizar_bic, normalizar_iban, validar_bic, validar_iban

IBANS_VALIDOS = [
    "ES9121000418450200051332",
    "ES7620770024003102575766",
    "DE89370400440532013000",  # IBAN alemán, para comprobar que no está sesgado a España
    "FR1420041010050500013M02606",  # IBAN francés, incluye letras en el BBAN
]


@pytest.mark.parametrize("iban", IBANS_VALIDOS)
def test_iban_valido_no_lanza_error(iban):
    validar_iban(iban)  # no debe lanzar nada


def test_iban_con_digito_de_control_incorrecto_se_rechaza():
    # Mismo IBAN que uno válido, pero con el último dígito cambiado: formato correcto,
    # checksum incorrecto — esto es justo lo que el XSD oficial NO detecta por sí solo.
    with pytest.raises(ValueError, match="dígito de control"):
        validar_iban("ES9121000418450200051333")


def test_iban_con_formato_invalido_se_rechaza():
    with pytest.raises(ValueError, match="formato inválido"):
        validar_iban("NOESUNIBAN")


def test_iban_demasiado_corto_se_rechaza():
    with pytest.raises(ValueError, match="longitud"):
        validar_iban("ES912100")


def test_normalizar_iban_quita_espacios_y_pone_mayusculas():
    assert normalizar_iban(" es91 2100 0418 4502 0005 1332 ") == "ES9121000418450200051332"


def test_bic_valido_de_8_caracteres_no_lanza_error():
    validar_bic("CAIXESBB")


def test_bic_valido_de_11_caracteres_no_lanza_error():
    validar_bic("CAIXESBBXXX")


def test_bic_demasiado_corto_se_rechaza():
    with pytest.raises(ValueError, match="formato inválido"):
        validar_bic("CAIXES")


def test_bic_con_pais_no_alfabetico_se_rechaza():
    with pytest.raises(ValueError, match="formato inválido"):
        validar_bic("CAIX12BB")


def test_normalizar_bic_quita_espacios_y_pone_mayusculas():
    assert normalizar_bic(" caixesbbxxx ") == "CAIXESBBXXX"
