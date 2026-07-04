from app.config import cargar_configuracion


def test_configuracion_por_defecto_si_no_existe_el_archivo(tmp_path):
    config = cargar_configuracion(ruta=tmp_path / "no_existe.py")

    assert config.modo_envio == "prueba"
    assert config.email_prueba is None


def test_carga_modo_envio_y_email_prueba_del_archivo(tmp_path):
    ruta = tmp_path / "config.local.py"
    ruta.write_text('MODO_ENVIO = "produccion"\nEMAIL_PRUEBA = "prueba@example.com"\n')

    config = cargar_configuracion(ruta=ruta)

    assert config.modo_envio == "produccion"
    assert config.email_prueba == "prueba@example.com"


def test_modo_envio_invalido_cae_a_prueba_por_seguridad(tmp_path):
    ruta = tmp_path / "config.local.py"
    ruta.write_text('MODO_ENVIO = "algo-que-no-es-valido"\n')

    config = cargar_configuracion(ruta=ruta)

    assert config.modo_envio == "prueba"


def test_archivo_sin_modo_envio_cae_a_prueba_por_seguridad(tmp_path):
    ruta = tmp_path / "config.local.py"
    ruta.write_text('EMAIL_PRUEBA = "prueba@example.com"\n')

    config = cargar_configuracion(ruta=ruta)

    assert config.modo_envio == "prueba"
    assert config.email_prueba == "prueba@example.com"
