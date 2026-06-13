"""
Reimport vehicles through the Fleet REST API.

This uploads the whole vehicle CSV to /api/v1/fleet/vehicles/import-csv so the
backend can create new vehicles and update existing ones in one pass.

Usage:
  python scripts/import_vehicles_api.py --api https://carro-taller-backend.onrender.com --user admin@fleet.com --pass "<password>"
"""
import argparse
import io
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
    candidates = sorted(workspace.glob("*Disponibles*.csv"))
    if candidates:
        return candidates[-1]
    raise FileNotFoundError("No se encontro el CSV de vehiculos disponibles")


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


def import_vehicles(api: str, token: str, csv_path: Path) -> None:
    headers = {"Authorization": f"Bearer {token}"}
    print(f"Archivo: {csv_path}")
    print("Enviando CSV al importador masivo del backend...")

    with csv_path.open("rb") as file:
        response = requests.post(
            f"{api.rstrip('/')}/api/v1/fleet/vehicles/import-csv",
            headers=headers,
            files={"file": (csv_path.name, file, "text/csv")},
            timeout=120,
        )

    if response.status_code not in (200, 201):
        print(f"Importacion fallida: {response.status_code} {response.text}")
        sys.exit(1)

    result = response.json()
    errors = result.get("errors") or []
    print("\nResultado:")
    print(f"  creados:      {result.get('created', 0)}")
    print(f"  actualizados: {result.get('updated', 0)}")
    print(f"  omitidos:     {result.get('skipped', 0)}")
    print(f"  errores:      {len(errors)}")
    for error in errors[:20]:
        print(f"  - {error}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="https://carro-taller-backend.onrender.com")
    parser.add_argument("--user", default="admin@fleet.com")
    parser.add_argument("--pass", dest="password", required=True)
    parser.add_argument("--csv", default=None)
    args = parser.parse_args()

    csv_path = Path(args.csv) if args.csv else find_csv()
    print(f"API: {args.api}")
    token = login(args.api, args.user, args.password)
    import_vehicles(args.api, token, csv_path)


if __name__ == "__main__":
    main()
