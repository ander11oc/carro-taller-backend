"""
Reimport CloudFleet tire catalog rows through the Fleet REST API.

The backend can mount tires only when each row includes vehicle and position,
either in explicit columns or inside Ubicacion like:
  Montada
  Vehiculo: JUY925
  Posicion: 2
"""
import argparse
import csv
import io
import re
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

try:
    import requests
except ImportError:
    import subprocess

    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests", "-q"])
    import requests


def find_csv() -> Path:
    workspace = Path("C:/RECUPERADOS/PROYECTOS/CARRO TALLER")
    candidates = sorted(workspace.glob("*ListaLlantas*.csv"))
    if candidates:
        return candidates[-1]
    raise FileNotFoundError("No se encontro el CSV de listado de llantas")


def login(api: str, username: str, password: str) -> str:
    response = requests.post(
        f"{api.rstrip('/')}/api/v1/auth/login",
        json={"email": username, "password": password},
        timeout=30,
    )
    if response.status_code != 200:
        print(f"Login fallido: {response.status_code} {response.text}")
        sys.exit(1)
    token = response.json().get("access_token") or response.json().get("token")
    if not token:
        print("Login sin token de acceso.")
        sys.exit(1)
    print("[OK] Login exitoso")
    return token


def read_catalog(csv_path: Path) -> list[dict[str, str]]:
    raw = csv_path.read_bytes()
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("utf-8", errors="replace")

    lines = text.splitlines()
    header_index = None
    for index, line in enumerate(lines):
        if "Llanta" in line and "Ubic" in line and "Proveedor" in line:
            header_index = index
            break
    if header_index is None:
        raise ValueError("No se encontro encabezado de catalogo de llantas.")

    reader = csv.DictReader(io.StringIO("\n".join(lines[header_index:])), delimiter=";")
    return [{key: (value or "").strip() for key, value in row.items() if key} for row in reader]


def has_mount_reference(row: dict[str, str]) -> bool:
    joined = " ".join(row.values())
    return bool(
        re.search(r"veh[ií]culo\s*:", joined, flags=re.IGNORECASE)
        and re.search(r"posici[oó]n\s*:", joined, flags=re.IGNORECASE)
    )


def post_json(api: str, token: str, path: str, payload: dict, timeout: int = 120) -> dict:
    response = requests.post(
        f"{api.rstrip('/')}{path}",
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
        timeout=timeout,
    )
    if response.status_code not in (200, 201):
        print(f"Error API {response.status_code}: {response.text}")
        sys.exit(1)
    return response.json()


def merge_result(total: dict | None, result: dict) -> dict:
    if total is None:
        total = {
            "total_rows": 0,
            "created_tires": 0,
            "updated_tires": 0,
            "created_vehicles": 0,
            "created_positions": 0,
            "created_events": 0,
            "skipped_rows": 0,
            "errors": [],
        }
    for key in ("total_rows", "created_tires", "updated_tires", "created_vehicles", "created_positions", "created_events", "skipped_rows"):
        total[key] += int(result.get(key, 0) or 0)
    total["errors"].extend(result.get("errors") or [])
    return total


def import_catalog(api: str, token: str, csv_path: Path, batch_size: int, dry_run: bool) -> None:
    rows = read_catalog(csv_path)
    rows_with_mount = [row for row in rows if has_mount_reference(row)]

    print(f"Archivo: {csv_path}")
    print(f"Filas leidas: {len(rows)}")
    print(f"Filas con Vehiculo/Posicion en Ubicacion: {len(rows_with_mount)}")

    if not rows_with_mount:
        print("\nNo importo nada: este CSV no trae Vehiculo/Posicion dentro de Ubicacion.")
        print("Necesitas exportar desde CloudFleet incluyendo el detalle de Ubicacion que se ve en pantalla.")
        return

    preview = post_json(api, token, "/api/v1/fleet/tires/master/preview", {"rows": rows_with_mount})
    print("\nPreview:")
    print(f"  validas:      {preview.get('valid_count', 0)}")
    print(f"  incompletas:  {preview.get('incomplete_count', 0)}")
    print(f"  duplicados:   {len(preview.get('duplicate_serials') or [])}")
    if dry_run:
        return

    batch_id = f"catalog-llantas-{csv_path.stem}"
    merged = None
    for start in range(0, len(rows_with_mount), batch_size):
        batch = rows_with_mount[start:start + batch_size]
        result = post_json(
            api,
            token,
            "/api/v1/fleet/tires/master/import",
            {
                "rows": batch,
                "source_sheet": csv_path.stem,
                "import_batch_id": batch_id,
                "source_row_start": start + 2,
            },
        )
        merged = merge_result(merged, result)
        print(f"Bloque {start // batch_size + 1}: {len(batch)} filas procesadas")

    print("\nResultado:")
    print(f"  creadas:       {merged.get('created_tires', 0)}")
    print(f"  actualizadas:  {merged.get('updated_tires', 0)}")
    print(f"  vehiculos:     {merged.get('created_vehicles', 0)}")
    print(f"  posiciones:    {merged.get('created_positions', 0)}")
    print(f"  eventos:       {merged.get('created_events', 0)}")
    print(f"  omitidas:      {merged.get('skipped_rows', 0)}")
    errors = merged.get("errors") or []
    print(f"  errores:       {len(errors)}")
    for error in errors[:20]:
        print(f"  - {error}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="https://carro-taller-backend.onrender.com")
    parser.add_argument("--user", default="admin@fleet.com")
    parser.add_argument("--pass", dest="password", required=True)
    parser.add_argument("--csv", default=None)
    parser.add_argument("--batch-size", type=int, default=200)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    csv_path = Path(args.csv) if args.csv else find_csv()
    print(f"API: {args.api}")
    token = login(args.api, args.user, args.password)
    import_catalog(args.api, token, csv_path, args.batch_size, args.dry_run)


if __name__ == "__main__":
    main()
