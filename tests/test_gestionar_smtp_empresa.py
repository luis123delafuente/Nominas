"""No existía ningún test para este script (ni para el resto de scripts/*.py de un solo
uso) antes de esta prueba — se crea aquí porque el criterio de calidad pedido exige
demostrar que el alta funciona de forma interactiva (getpass) sin pasar la contraseña
como argumento."""

import pytest

import scripts.gestionar_smtp_empresa as script_smtp
from app.db import crear_empresa, descifrar_credenciales_smtp, get_connection, obtener_credenciales_smtp


@pytest.fixture
def ruta_db(tmp_path):
    return tmp_path / "test_nominas.db"


@pytest.fixture
def ruta_clave(tmp_path):
    return tmp_path / "clave_cifrado.key"


@pytest.fixture(autouse=True)
def _aislar_bd_y_clave(monkeypatch, ruta_db, ruta_clave):
    """Aísla el script de data/nominas.db y data/clave_cifrado.key reales."""
    monkeypatch.setattr(script_smtp, "get_connection", lambda: get_connection(ruta_db))
    monkeypatch.setattr("app.crypto_campos.RUTA_CLAVE_POR_DEFECTO", ruta_clave)


@pytest.fixture
def nif_empresa(ruta_db):
    conn = get_connection(ruta_db)
    try:
        crear_empresa(conn, "MEDIFORM PLUS S.L.", "B82827635")
    finally:
        conn.close()
    return "B82827635"


def test_alta_pide_la_password_por_getpass_y_no_por_argumento(monkeypatch, ruta_db, nif_empresa):
    llamadas_getpass = []

    def _getpass_falso(prompt=""):
        llamadas_getpass.append(prompt)
        return "abcd efgh ijkl mnop"

    monkeypatch.setattr(script_smtp.getpass, "getpass", _getpass_falso)

    # Ni "puerto" ni ningún otro argumento incluye la contraseña: solo 5 argumentos
    # (accion, nif, host, puerto, usuario), no 6.
    script_smtp.main(["alta", nif_empresa, "smtp.gmail.com", "587", "empresa@gmail.com"])

    assert len(llamadas_getpass) == 1  # se pidió exactamente una vez, de forma interactiva

    conn = get_connection(ruta_db)
    try:
        fila = obtener_credenciales_smtp(conn, 1)
        assert fila["host"] == "smtp.gmail.com"
        assert fila["puerto"] == 587
        assert fila["usuario"] == "empresa@gmail.com"
        assert fila["password_cifrado"] != "abcd efgh ijkl mnop"  # nunca en claro en la BD

        descifrada = descifrar_credenciales_smtp(fila)
        assert descifrada["password"] == "abcd efgh ijkl mnop"
    finally:
        conn.close()


def test_alta_con_empresa_inexistente_no_guarda_ninguna_credencial(monkeypatch, ruta_db, capsys):
    monkeypatch.setattr(script_smtp.getpass, "getpass", lambda prompt="": "clave")

    script_smtp.main(["alta", "Z00000000", "smtp.gmail.com", "587", "empresa@gmail.com"])

    salida = capsys.readouterr().out
    assert "No existe ninguna empresa" in salida
    conn = get_connection(ruta_db)
    try:
        assert conn.execute("SELECT COUNT(*) AS n FROM credenciales_smtp").fetchone()["n"] == 0
    finally:
        conn.close()


def test_alta_rechaza_puerto_invalido_sin_guardar_nada(monkeypatch, ruta_db, nif_empresa, capsys):
    monkeypatch.setattr(script_smtp.getpass, "getpass", lambda prompt="": "clave-cualquiera")

    script_smtp.main(["alta", nif_empresa, "smtp.gmail.com", "99999", "empresa@gmail.com"])

    salida = capsys.readouterr().out
    assert "Error" in salida

    conn = get_connection(ruta_db)
    try:
        assert conn.execute("SELECT COUNT(*) AS n FROM credenciales_smtp").fetchone()["n"] == 0
    finally:
        conn.close()


def test_listar_nunca_muestra_la_password_en_claro(monkeypatch, ruta_db, nif_empresa, capsys):
    monkeypatch.setattr(script_smtp.getpass, "getpass", lambda prompt="": "contraseña-super-secreta")
    script_smtp.main(["alta", nif_empresa, "smtp.gmail.com", "587", "empresa@gmail.com"])
    capsys.readouterr()  # descarta la salida del alta

    script_smtp.main(["listar", nif_empresa])

    salida = capsys.readouterr().out
    assert "contraseña-super-secreta" not in salida
    assert "empresa@gmail.com" in salida
    assert "oculta" in salida
