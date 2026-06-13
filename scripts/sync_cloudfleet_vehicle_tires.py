"""
Synchronize current tire mounts from CloudFleet into the local backend.

CloudFleet credentials are not stored here. The script opens a persistent
Playwright profile; log in manually the first time, then reuse the same profile.

Usage:
  python scripts/sync_cloudfleet_vehicle_tires.py --api https://carro-taller-backend.onrender.com --user admin@fleet.com --pass "<backend-password>" --plate JKV615
  python scripts/sync_cloudfleet_vehicle_tires.py --api https://carro-taller-backend.onrender.com --user admin@fleet.com --pass "<backend-password>" --limit 5
  python scripts/sync_cloudfleet_vehicle_tires.py --api https://carro-taller-backend.onrender.com --user admin@fleet.com --pass "<backend-password>"
"""
import argparse
import csv
import io
import json
import os
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

try:
    import requests
except ImportError:
    import subprocess

    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests", "-q"])
    import requests

try:
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright
except ImportError:
    PlaywrightError = Exception
    PlaywrightTimeoutError = None
    sync_playwright = None


CLOUDFLEET_URL = "https://fleet.cloudfleet.com/App/Seguras/Interno/Llantas/LlantasVehiculo.aspx"
DEFAULT_PROFILE = Path(os.environ.get("LOCALAPPDATA", ".")) / "carro-taller-cloudfleet-profile"


def login(api: str, username: str, password: str) -> str:
    response = requests.post(
        f"{api.rstrip('/')}/api/v1/auth/login",
        json={"email": username, "password": password},
        timeout=30,
    )
    if response.status_code != 200:
        print(f"Login backend fallido: {response.status_code} {response.text}")
        sys.exit(1)
    token = response.json().get("access_token") or response.json().get("token")
    if not token:
        print("Login backend sin token de acceso.")
        sys.exit(1)
    print("[OK] Login backend exitoso")
    return token


def get_json(api: str, token: str, path: str) -> Any:
    response = requests.get(
        f"{api.rstrip('/')}{path}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=60,
    )
    if response.status_code != 200:
        raise RuntimeError(f"GET {path} fallo: {response.status_code} {response.text}")
    return response.json()


def post_json(api: str, token: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    response = requests.post(
        f"{api.rstrip('/')}{path}",
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
        timeout=120,
    )
    if response.status_code not in (200, 201):
        raise RuntimeError(f"POST {path} fallo: {response.status_code} {response.text}")
    return response.json()


def load_vehicle_plates(api: str, token: str, requested: list[str], limit: int | None) -> list[str]:
    if requested:
        plates = [plate.strip().upper() for plate in requested if plate.strip()]
        return plates[:limit] if limit else plates
    rows = get_json(api, token, "/api/v1/fleet/vehicles?limit=500")
    plates = sorted({str(row.get("plate", "")).strip().upper() for row in rows if row.get("plate")})
    return plates[:limit] if limit else plates


def parse_number(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text or text in {"-", "--", "N/D"}:
        return None
    text = re.sub(r"[^0-9,.\-]", "", text)
    if not text:
        return None
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")
    elif "." in text and len(text.rsplit(".", 1)[-1]) == 3:
        text = text.replace(".", "")
    elif text.count(".") > 1:
        text = text.replace(".", "")
    try:
        return float(text)
    except ValueError:
        return None


def parse_money(value: Any) -> float | None:
    return parse_number(value)


def parse_cloudfleet_date(value: Any) -> str | None:
    text = " ".join(str(value or "").strip().split())
    if not text or text in {"-", "--", "N/D"}:
        return None
    text = text.split(" ", 1)[0]
    month_map = {
        "ene": "01",
        "feb": "02",
        "mar": "03",
        "abr": "04",
        "may": "05",
        "jun": "06",
        "jul": "07",
        "ago": "08",
        "sep": "09",
        "oct": "10",
        "nov": "11",
        "dic": "12",
    }
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            pass
    match = re.match(r"(\d{1,2})/([A-Za-z]{3})\.?/(\d{4})", text, flags=re.IGNORECASE)
    if match:
        day, mon, year = match.groups()
        month = month_map.get(mon.lower()[:3])
        if month:
            return date(int(year), int(month), int(day)).isoformat()
    return None


def normalize_header(value: str) -> str:
    import unicodedata

    normalized = unicodedata.normalize("NFKD", value or "")
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    return "".join(char.lower() for char in normalized if char.isalnum())


def pick(row: dict[str, str], *names: str) -> str:
    normalized = {normalize_header(key): value for key, value in row.items()}
    for name in names:
        value = normalized.get(normalize_header(name))
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def normalize_mount_row(row: dict[str, str]) -> dict[str, Any] | None:
    code = pick(row, "Cod.", "Cod", "Codigo Llanta", "Codigo", "Código")
    position = pick(row, "Pos.", "Pos", "Posicion", "Posición")
    label = pick(row, "Llanta", "Descripcion", "Descripción")
    if not code or not position or "total" in position.lower() or "promedio" in position.lower():
        return None
    return {
        "position": position.replace("(Rep)", "").strip(),
        "code": code,
        "tire_label": label,
        "life_code": pick(row, "Cod. Vida", "Codigo Vida", "Código Vida") or "VN",
        "mount_date": parse_cloudfleet_date(pick(row, "Fech.Montaje", "Fecha Montaje")),
        "mount_mileage": parse_number(pick(row, "Medicion Montaje", "Medición Montaje")),
        "last_tread_date": parse_cloudfleet_date(pick(row, "Fech. Ultima Profundidad", "Fech. Última Profundidad")),
        "last_tread_km": parse_number(pick(row, "km.Ultima Profundidad", "km.Última Profundidad")),
        "km_total": parse_number(pick(row, "km.Recorr. total", "km Recorr total")),
        "km_in_vehicle": parse_number(pick(row, "km.Recorr. en Vehiculo", "km.Recorr. en Vehículo")),
        "tire_cost": parse_money(pick(row, "Costo Llanta")),
        "original_tread_mm": parse_number(pick(row, "Prof. Original")),
        "effective_tread_mm": parse_number(pick(row, "Prof. Efectiva")),
        "lowest_tread_mm": parse_number(pick(row, "Prof. Mas Baja", "Prof. Más Baja")),
        "tread_worn_mm": parse_number(pick(row, "mm Gastados")),
        "km_per_mm_total": parse_number(pick(row, "km/mm Total")),
        "cost_per_mm": parse_money(pick(row, "Costo/mm")),
        "cpkm_proportional": parse_money(pick(row, "CPkm Proporcional")),
        "cpkm_real": parse_money(pick(row, "CPkm Real")),
        "projected_km": parse_number(pick(row, "km proyec.", "km proyec")),
        "provider": pick(row, "Proveedor"),
    }


def ensure_playwright() -> None:
    if sync_playwright is not None:
        return
    print("Falta Playwright en este entorno.")
    print("Ejecuta:")
    print(f"  {sys.executable} -m pip install playwright")
    print(f"  {sys.executable} -m playwright install chromium")
    sys.exit(1)


def has_vehicle_input(page) -> bool:
    return bool(
        page.evaluate(
            """
            () => !!document.querySelector('#c_ctlMenuLlantasXVehiculo1_ctlVehicle_TxtPlaca')
            """
        )
    )


def is_cloudfleet_login_page(page) -> bool:
    return bool(
        page.evaluate(
            """
            () => {
              const text = document.body ? document.body.innerText.toLowerCase() : '';
              const url = window.location.href.toLowerCase();
              return (
                url.includes('/account/default.aspx') ||
                url.includes('returnurl=') ||
                text.includes('alias de tu cuenta') ||
                text.includes('iniciar sesión') ||
                text.includes('iniciar sesion') ||
                !!document.querySelector('#c_TxtAccountAlias, input[name*="TxtAccountAlias"], input[name*="cmdLogin"]')
              );
            }
            """
        )
    )


def is_vehicle_tires_page(page) -> bool:
    return bool(
        page.evaluate(
            """
            () => {
              const text = document.body ? document.body.innerText.toLowerCase() : '';
              const url = window.location.href.toLowerCase();
              return (
                url.includes('/llantas/llantasvehiculo.aspx') &&
                !text.includes('alias de tu cuenta') &&
                (text.includes('llantas del vehículo') || text.includes('llantas del vehiculo'))
              );
            }
            """
        )
    )


def goto_cloudfleet_page(page, url: str) -> None:
    last_error = None
    for _ in range(3):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_load_state("domcontentloaded", timeout=30000)
            page.wait_for_timeout(1000)
            return
        except PlaywrightError as exc:
            last_error = exc
            message = str(exc).lower()
            if "interrupted by another navigation" not in message:
                raise
            page.wait_for_timeout(2500)
            try:
                page.wait_for_load_state("domcontentloaded", timeout=30000)
            except PlaywrightError:
                pass
    if last_error:
        raise last_error


def wait_for_cloudfleet_session(page, url: str, headless: bool) -> None:
    goto_cloudfleet_page(page, url)
    if is_vehicle_tires_page(page):
        return
    if headless:
        raise RuntimeError("CloudFleet no esta autenticado en el perfil Playwright. Ejecuta sin --headless y entra manualmente.")
    while not is_vehicle_tires_page(page):
        if is_cloudfleet_login_page(page):
            print("\nCloudFleet esta en pantalla de login.")
            print("Inicia sesion completamente en la ventana del navegador.")
        else:
            print("\nAun no estoy en Llantas del Vehiculo.")
            print("Navega en CloudFleet hasta Llantas > Llantas del Vehiculo.")
        input("Cuando ya veas 'Llantas del Vehiculo' en el navegador, presiona ENTER aqui...")
        goto_cloudfleet_page(page, url)
    if not has_vehicle_input(page):
        raise RuntimeError("Estoy en Llantas del Vehiculo, pero no encontre el input de vehiculo.")


def search_vehicle_legacy(page, plate: str) -> None:
    page.goto(CLOUDFLEET_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(500)
    page.evaluate(
        """
        (plate) => {
          const visibleInputs = Array.from(document.querySelectorAll('input'))
            .filter(input => input.offsetParent !== null && ['text', 'search', ''].includes(input.type || ''));
          const vehicleInput = visibleInputs[0];
          if (!vehicleInput) throw new Error('No se encontro input de vehiculo.');
          vehicleInput.focus();
          vehicleInput.value = plate;
          vehicleInput.dispatchEvent(new Event('input', { bubbles: true }));
          vehicleInput.dispatchEvent(new Event('change', { bubbles: true }));
        }
        """,
        plate,
    )
    try:
        page.keyboard.press("Enter")
    except Exception:
        pass
    page.wait_for_timeout(500)
    page.evaluate(
        """
        () => {
          const candidates = Array.from(document.querySelectorAll('button, input[type=button], input[type=submit], a'))
            .filter(el => el.offsetParent !== null);
          const searchButton = candidates.find(el => {
            const text = ((el.innerText || el.value || el.title || el.getAttribute('aria-label') || '') + '').toLowerCase();
            return text.includes('buscar') || text.includes('>') || text.includes('»');
          });
          if (searchButton) searchButton.click();
        }
        """
    )
    page.wait_for_timeout(2500)


def search_vehicle(page, plate: str) -> None:
    goto_cloudfleet_page(page, CLOUDFLEET_URL)
    vehicle_selector = "#c_ctlMenuLlantasXVehiculo1_ctlVehicle_TxtPlaca"
    button_selector = "#c_ctlMenuLlantasXVehiculo1_cmdFindVehicle"
    page.wait_for_selector(vehicle_selector, timeout=30000)
    page.fill(vehicle_selector, "")
    page.fill(vehicle_selector, plate)
    page.evaluate(
        """
        (selector) => {
          const input = document.querySelector(selector);
          if (!input) throw new Error('No se encontro input real de vehiculo.');
          input.dispatchEvent(new Event('input', { bubbles: true }));
          input.dispatchEvent(new Event('change', { bubbles: true }));
        }
        """,
        vehicle_selector,
    )
    page.wait_for_timeout(300)
    try:
        with page.expect_navigation(wait_until="domcontentloaded", timeout=20000):
            page.click(button_selector)
    except PlaywrightError as exc:
        if "timeout" not in str(exc).lower():
            raise
    page.wait_for_load_state("domcontentloaded", timeout=30000)
    page.wait_for_timeout(2500)


def extract_mount_rows_legacy(page) -> list[dict[str, Any]]:
    raw_rows = page.evaluate(
        """
        () => {
          const clean = (value) => (value || '').replace(/\\s+/g, ' ').trim();
          const tables = Array.from(document.querySelectorAll('table'));
          for (const table of tables) {
            const allRows = Array.from(table.querySelectorAll('tr'));
            if (!allRows.length) continue;
            let headerCells = Array.from(allRows[0].querySelectorAll('th,td')).map(cell => clean(cell.innerText));
            let headerIndex = 0;
            for (let i = 0; i < Math.min(3, allRows.length); i++) {
              const candidate = Array.from(allRows[i].querySelectorAll('th,td')).map(cell => clean(cell.innerText));
              const joined = candidate.join(' ').toLowerCase();
              if (joined.includes('pos') && joined.includes('cod') && joined.includes('llanta')) {
                headerCells = candidate;
                headerIndex = i;
                break;
              }
            }
            const headerText = headerCells.join(' ').toLowerCase();
            if (!headerText.includes('pos') || !headerText.includes('cod') || !headerText.includes('llanta')) continue;
            return allRows.slice(headerIndex + 1).map(row => {
              const cells = Array.from(row.querySelectorAll('td')).map(cell => clean(cell.innerText));
              const item = {};
              headerCells.forEach((header, index) => { item[header || `col_${index}`] = cells[index] || ''; });
              return item;
            }).filter(item => Object.values(item).some(Boolean));
          }
          return [];
        }
        """
    )
    normalized = []
    for row in raw_rows:
        item = normalize_mount_row(row)
        if item:
            normalized.append(item)
    return normalized


def extract_mount_rows(page) -> list[dict[str, Any]]:
    raw_rows = page.evaluate(
        """
        () => {
          const table = document.querySelector('#c_grdLlantas');
          if (!table) return [];
          const clean = (value) => (value || '').replace(/\\s+/g, ' ').trim();
          const headers = Array.from(table.querySelectorAll(':scope > thead > tr > th'))
            .map((cell, index) => clean(cell.innerText) || `col_${index}`);
          return Array.from(table.querySelectorAll(':scope > tbody > tr')).map(row => {
            const cells = Array.from(row.querySelectorAll(':scope > td')).map(cell => clean(cell.innerText));
            const item = {};
            headers.forEach((header, index) => { item[header] = cells[index] || ''; });
            return item;
          }).filter(item => {
            const position = (item['Pos.'] || '').trim();
            const code = (item['Cod.'] || '').trim();
            return position && code && !position.toLowerCase().includes('total');
          });
        }
        """
    )
    normalized = []
    for row in raw_rows:
        item = normalize_mount_row(row)
        if item:
            normalized.append(item)
    return normalized


def page_confirms_no_mounts(page) -> bool:
    text = page.evaluate("() => document.body ? document.body.innerText : ''")
    compact = " ".join(str(text or "").split()).lower()
    return (
        "no existen llantas montadas" in compact
        or "sin llantas montadas" in compact
        or "no tiene llantas montadas" in compact
    )


def page_mentions_plate(page, plate: str) -> bool:
    text = page.evaluate("() => document.body ? document.body.innerText : ''")
    return plate.upper() in str(text or "").upper()


def save_page_evidence(page, evidence_dir: Path, plate: str, suffix: str) -> dict[str, str]:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    base = evidence_dir / f"{plate}-{suffix}"
    screenshot = str(base.with_suffix(".png"))
    html_path = str(base.with_suffix(".html"))
    try:
        page.screenshot(path=screenshot, full_page=True)
    except Exception:
        screenshot = ""
    try:
        Path(html_path).write_text(page.content(), encoding="utf-8", errors="replace")
    except Exception:
        html_path = ""
    return {"screenshot": screenshot, "html": html_path}


def sync_plate(api: str, token: str, page, plate: str, source: str, evidence_dir: Path | None) -> dict[str, Any]:
    try:
        search_vehicle(page, plate)
        rows = extract_mount_rows(page)
        no_mounts_confirmed = page_confirms_no_mounts(page)
        plate_loaded = page_mentions_plate(page, plate)
        evidence = {}
        if evidence_dir:
            evidence = save_page_evidence(page, evidence_dir, plate, "ok" if rows else "empty")
        if not rows and not no_mounts_confirmed:
            raise RuntimeError(
                "No se extrajeron montajes y CloudFleet no confirmo vehiculo sin montajes. "
                "No se sincroniza para evitar desmontar datos validos."
            )
        result = post_json(
            api,
            token,
            "/api/v1/fleet/vehicle-tire-mounts/sync",
            {
                "plate": plate,
                "mounted": rows,
                "source": source,
                "clear_missing": bool(rows or (no_mounts_confirmed and plate_loaded)),
            },
        )
        result["mounted_rows"] = len(rows)
        result["no_mounts_confirmed"] = no_mounts_confirmed
        result["plate_loaded"] = plate_loaded
        result.update(evidence)
        result["status"] = "ok"
        print(f"[OK] {plate}: {len(rows)} montajes")
        return result
    except Exception as exc:
        evidence = {}
        if evidence_dir:
            evidence = save_page_evidence(page, evidence_dir, plate, "error")
        print(f"[ERROR] {plate}: {exc}")
        return {"plate": plate, "status": "error", "error": str(exc), **evidence}


def write_reports(report_base: Path, rows: list[dict[str, Any]]) -> None:
    report_base.parent.mkdir(parents=True, exist_ok=True)
    json_path = report_base.with_suffix(".json")
    csv_path = report_base.with_suffix(".csv")
    json_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    keys = sorted({key for row in rows for key in row.keys()})
    with csv_path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nReporte JSON: {json_path}")
    print(f"Reporte CSV:  {csv_path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="https://carro-taller-backend.onrender.com")
    parser.add_argument("--user", default="admin@fleet.com")
    parser.add_argument("--pass", dest="password", required=True)
    parser.add_argument("--cloudfleet-url", default=CLOUDFLEET_URL)
    parser.add_argument("--profile-dir", default=str(DEFAULT_PROFILE))
    parser.add_argument("--plate", action="append", default=[])
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--report", default="reports/cloudfleet_vehicle_tire_sync")
    parser.add_argument("--screenshots", default="reports/cloudfleet_sync_errors")
    args = parser.parse_args()

    ensure_playwright()
    token = login(args.api, args.user, args.password)
    plates = load_vehicle_plates(args.api, token, args.plate, args.limit)
    print(f"Placas a procesar: {len(plates)}")
    if not plates:
        return

    report_rows: list[dict[str, Any]] = []
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            args.profile_dir,
            headless=args.headless,
            viewport={"width": 1600, "height": 900},
        )
        page = context.pages[0] if context.pages else context.new_page()
        wait_for_cloudfleet_session(page, args.cloudfleet_url, args.headless)
        for plate in plates:
            report_rows.append(
                sync_plate(
                    args.api,
                    token,
                    page,
                    plate,
                    "cloudfleet-vehicle-tires",
                    Path(args.screenshots) if args.screenshots else None,
                )
            )
        context.close()

    write_reports(Path(args.report), report_rows)
    ok_count = sum(1 for row in report_rows if row.get("status") == "ok")
    error_count = sum(1 for row in report_rows if row.get("status") == "error")
    mounted_count = sum(int(row.get("mounted_rows") or 0) for row in report_rows)
    no_mounts = sum(1 for row in report_rows if row.get("status") == "ok" and int(row.get("mounted_rows") or 0) == 0)
    print("\nResumen:")
    print(f"  procesadas:    {ok_count}")
    print(f"  sin montajes:  {no_mounts}")
    print(f"  llantas sync:  {mounted_count}")
    print(f"  errores:       {error_count}")


if __name__ == "__main__":
    main()
