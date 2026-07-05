import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_importar_app_main_no_crea_ni_toca_la_base_de_datos_por_defecto(tmp_path):
    """Antes, `app/main.py` inicializaba el esquema (get_connection().close()) a nivel
    de módulo: el simple `import app.main` disparaba init_db() contra data/nominas.db,
    incluso sin arrancar ningún servidor. Ahora esa inicialización vive en el `lifespan`
    de FastAPI, que solo se dispara cuando el servidor arranca de verdad (o cuando un
    TestClient se usa como context manager).

    Para probarlo sin arriesgar la base de datos real del proyecto, copiamos solo el
    paquete `app/` a una carpeta temporal y lo importamos ahí en un proceso aparte:
    si el import no toca nada, `data/nominas.db` (relativo a esa copia) no debe existir.
    """
    destino = tmp_path / "proyecto_aislado"
    shutil.copytree(PROJECT_ROOT / "app", destino / "app")

    ruta_db_relativa = destino / "data" / "nominas.db"
    assert not ruta_db_relativa.exists()

    resultado = subprocess.run(
        [sys.executable, "-c", "import app.main"],
        cwd=destino,
        capture_output=True,
        text=True,
    )

    assert resultado.returncode == 0, f"El import falló:\n{resultado.stderr}"
    assert not ruta_db_relativa.exists(), "Importar app.main no debe crear ni tocar data/nominas.db"
