import pytest

from app.crypto_campos import CifradoError, cifrar_campo, descifrar_campo


def test_cifrar_y_descifrar_devuelve_el_valor_original(tmp_path):
    ruta_clave = tmp_path / "clave.key"

    cifrado = cifrar_campo("ES9121000418450200051332", ruta_clave=ruta_clave)

    assert cifrado != "ES9121000418450200051332"  # no se guarda en texto plano
    assert descifrar_campo(cifrado, ruta_clave=ruta_clave) == "ES9121000418450200051332"


def test_none_pasa_intacto_en_ambos_sentidos(tmp_path):
    ruta_clave = tmp_path / "clave.key"

    assert cifrar_campo(None, ruta_clave=ruta_clave) is None
    assert descifrar_campo(None, ruta_clave=ruta_clave) is None


def test_la_clave_se_genera_sola_la_primera_vez(tmp_path):
    ruta_clave = tmp_path / "clave.key"
    assert not ruta_clave.exists()

    cifrar_campo("dato", ruta_clave=ruta_clave)

    assert ruta_clave.exists()


def test_reutiliza_la_misma_clave_entre_llamadas(tmp_path):
    ruta_clave = tmp_path / "clave.key"

    cifrar_campo("primero", ruta_clave=ruta_clave)
    clave_tras_primera_llamada = ruta_clave.read_bytes()

    cifrar_campo("segundo", ruta_clave=ruta_clave)

    assert ruta_clave.read_bytes() == clave_tras_primera_llamada


def test_descifrar_con_clave_distinta_lanza_error_claro(tmp_path):
    ruta_clave_1 = tmp_path / "clave1.key"
    ruta_clave_2 = tmp_path / "clave2.key"

    cifrado = cifrar_campo("ES9121000418450200051332", ruta_clave=ruta_clave_1)

    with pytest.raises(CifradoError):
        descifrar_campo(cifrado, ruta_clave=ruta_clave_2)


def test_descifrar_valor_manipulado_lanza_error_en_vez_de_devolver_basura(tmp_path):
    ruta_clave = tmp_path / "clave.key"
    cifrado = cifrar_campo("ES9121000418450200051332", ruta_clave=ruta_clave)

    manipulado = cifrado[:-4] + "abcd"

    with pytest.raises(CifradoError):
        descifrar_campo(manipulado, ruta_clave=ruta_clave)
