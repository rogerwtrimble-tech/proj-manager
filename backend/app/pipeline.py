"""Migration data pipeline.

Flow (per migration date, folder 'Migration - mm.dd.yyyy' on SharePoint):
  stage     -> download the data ZIP via SharePoint/OneDrive URLs (Microsoft
               Graph; never mapped drives) into DATA_DIR/mig/<mm.dd.yyyy>/raw
               (demo mode: generates a realistic sample ZIP instead)
  normalize -> build Combined CSVs: addresses.csv, occupier.csv, utilities.csv
  precheck  -> dry-run validation; writes a [ERROR]/[WARNING] .txt log
  report    -> writes an .xlsx summary whose sheets list rows to fix;
               artifacts are also uploaded back to the SharePoint folder
               (live mode) under Results/

Raw input assumption (documented in README): the ZIP holds per city/state
CSVs of house records. Column aliases below cover the common header names;
extend ALIASES when a new raw layout shows up.
"""
import base64
import csv
import hashlib
import io
import json
import os
import re
import zipfile
from datetime import datetime, timezone

from .config import settings
from .graph_client import GraphError, graph_client

ALIASES = {
    "address": ["address", "street", "street_address", "property_address", "addr"],
    "city": ["city", "town"],
    "state": ["state", "st"],
    "zip": ["zip", "zipcode", "zip_code", "postal_code"],
    "price": ["price", "rent", "amount", "monthly_rent", "list_price"],
    "occupied": ["occupied", "occupancy", "is_occupied", "status"],
    "tenure": ["tenure", "owner_rental", "owner/rental", "type", "ownership"],
    "occupier_name": ["occupier", "occupier_name", "tenant", "tenant_name", "resident", "name", "people"],
    "occupier_email": ["email", "occupier_email", "tenant_email"],
    "occupier_cell": ["cell", "phone", "mobile", "occupier_cell", "tenant_phone"],
    "utility_type": ["utility_type", "utility", "utilities"],
    "utility_provider": ["utility_provider", "provider"],
    "utility_account": ["utility_account", "account_number", "account"],
    "utility_status": ["utility_status"],
}

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def mig_dir(migration_date: str) -> str:
    return os.path.join(settings.data_dir, "mig", migration_date)


def _pid(address: str, city: str, state: str) -> str:
    key = f"{address}|{city}|{state}".lower().encode()
    return "P" + hashlib.sha1(key).hexdigest()[:10]


def _pick(row: dict, field: str) -> str:
    for alias in ALIASES[field]:
        for key, value in row.items():
            if key and key.strip().lower() == alias and value is not None:
                return str(value).strip()
    return ""


def _truthy_occupied(value: str) -> bool | None:
    v = value.strip().lower()
    if v in {"yes", "true", "1", "occupied", "y"}:
        return True
    if v in {"no", "false", "0", "vacant", "n", ""}:
        return False if v != "" else None
    return None


# --------------------------------------------------------------------------
# Sample data (demo mode) — includes deliberate defects for the pre-check.
# --------------------------------------------------------------------------
SAMPLE_FILES = {
    "Denton, TX/houses.csv": (
        "address,city,state,zip,price,occupied,owner/rental,occupier,email,cell,utility_type,provider,account_number\n"
        "101 Oak St,Denton,TX,76201,1450,yes,rental,Jane Doe,jane@example.com,9405550101,electric,CoServ,887123\n"
        "205 Pine Ave,Denton,TX,76201,,yes,rental,Mark Roe,mark-at-example.com,9405550102,water,City of Denton,\n"
        "101 Oak St,Denton,TX,76201,1450,yes,rental,Jane Doe,jane@example.com,9405550101,electric,CoServ,887123\n"
    ),
    "Grapevine, TX/houses.csv": (
        "address,city,state,zip,price,occupied,owner/rental,occupier,email,cell,utility_type,provider,account_number\n"
        "55 Vine Ct,Grapevine,TX,76051,2100,no,owner,,,,,,\n"
        "900 Main St,Grapevine,TX,76051,not-a-price,yes,rental,,sam@example.com,8175550119,gas,Atmos,55190\n"
    ),
}


def sample_zip_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in SAMPLE_FILES.items():
            zf.writestr(name, content)
    return buf.getvalue()


# --------------------------------------------------------------------------
# Stage
# --------------------------------------------------------------------------
def _download_zip_from_sharepoint(folder_url: str) -> tuple[bytes, str]:
    """Download the first .zip found in the given SharePoint folder.

    folder_url may be the site-relative folder path
    (e.g. 'Shared Documents/Migration - 11.01.2026') resolved against
    SHAREPOINT_SITE_URL's default document library, or a full folder URL
    under the configured site. Uses Graph URLs only — no mapped drives.
    """
    site = graph_client.resolve_site()
    drive_id = graph_client.site_default_drive_id(site["id"])
    folder_path = folder_url
    if folder_url.startswith("http"):
        from urllib.parse import unquote, urlparse

        site_path = urlparse(settings.sharepoint_site_url).path.rstrip("/")
        url_path = unquote(urlparse(folder_url).path)
        folder_path = url_path[len(site_path):].strip("/") if url_path.startswith(site_path) else url_path.strip("/")
        # strip a leading library name if present (default drive root == library root)
        parts = folder_path.split("/")
        children = None
        for candidate in (folder_path, "/".join(parts[1:])):
            try:
                children = graph_client.list_folder_children_by_path(drive_id, candidate)
                folder_path = candidate
                break
            except GraphError:
                continue
        if children is None:
            raise GraphError(f"Could not list folder '{folder_url}' in the site's document library")
    else:
        children = graph_client.list_folder_children_by_path(drive_id, folder_path)
    zips = [c for c in children if str(c.get("name", "")).lower().endswith(".zip")]
    if not zips:
        raise GraphError(f"No .zip file found in folder '{folder_url}'")
    item = zips[0]
    return graph_client.download_item(drive_id, item["id"]), str(item["name"])


def stage(migration_date: str, folder_url: str, log) -> str:
    base = mig_dir(migration_date)
    raw_dir = os.path.join(base, "raw")
    os.makedirs(raw_dir, exist_ok=True)
    if graph_client.configured:
        data, name = _download_zip_from_sharepoint(folder_url)
        log(f"Downloaded {name} ({len(data)} bytes) from SharePoint folder URL.")
    else:
        data, name = sample_zip_bytes(), f"Migration - {migration_date}.zip (sample)"
        log("Demo mode: using generated sample ZIP (no Graph credentials configured).")
    zip_path = os.path.join(base, "source.zip")
    with open(zip_path, "wb") as fh:
        fh.write(data)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(raw_dir)
    count = sum(len(files) for _, _, files in os.walk(raw_dir))
    log(f"Staged {count} raw file(s) into {raw_dir}.")
    return base


# --------------------------------------------------------------------------
# Normalize -> Combined CSVs
# --------------------------------------------------------------------------
def normalize(migration_date: str, log) -> dict:
    base = mig_dir(migration_date)
    raw_dir = os.path.join(base, "raw")
    combined = os.path.join(base, "combined")
    os.makedirs(combined, exist_ok=True)
    addresses, occupiers, utilities = [], [], []
    seen_files = 0
    for root, _, files in os.walk(raw_dir):
        for fname in sorted(files):
            if not fname.lower().endswith(".csv"):
                continue
            seen_files += 1
            with open(os.path.join(root, fname), newline="", encoding="utf-8-sig") as fh:
                for row in csv.DictReader(fh):
                    address = _pick(row, "address")
                    city = _pick(row, "city")
                    state = _pick(row, "state")
                    if not address and not city:
                        continue
                    pid = _pid(address, city, state)
                    occ = _truthy_occupied(_pick(row, "occupied"))
                    addresses.append({
                        "property_id": pid, "address": address, "city": city, "state": state,
                        "zip": _pick(row, "zip"), "price": _pick(row, "price"),
                        "occupied": "" if occ is None else ("yes" if occ else "no"),
                        "tenure": _pick(row, "tenure"),
                    })
                    name = _pick(row, "occupier_name")
                    if name or _pick(row, "occupier_email"):
                        occupiers.append({
                            "property_id": pid, "name": name,
                            "email": _pick(row, "occupier_email"), "cell": _pick(row, "occupier_cell"),
                        })
                    if _pick(row, "utility_type") or _pick(row, "utility_provider"):
                        utilities.append({
                            "property_id": pid, "utility_type": _pick(row, "utility_type"),
                            "provider": _pick(row, "utility_provider"),
                            "account_number": _pick(row, "utility_account"),
                            "status": _pick(row, "utility_status"),
                        })
    def write(name: str, rows: list[dict], fields: list[str]) -> None:
        with open(os.path.join(combined, name), "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)

    write("addresses.csv", addresses, ["property_id", "address", "city", "state", "zip", "price", "occupied", "tenure"])
    write("occupier.csv", occupiers, ["property_id", "name", "email", "cell"])
    write("utilities.csv", utilities, ["property_id", "utility_type", "provider", "account_number", "status"])
    log(f"Normalized {seen_files} raw file(s): {len(addresses)} addresses, {len(occupiers)} occupiers, {len(utilities)} utilities -> {combined}.")
    return {"addresses": addresses, "occupier": occupiers, "utilities": utilities}


# --------------------------------------------------------------------------
# Pre-check (dry run)
# --------------------------------------------------------------------------
def precheck(data: dict) -> list[dict]:
    issues: list[dict] = []

    def add(level, file, row, field, message):
        issues.append({"level": level, "file": file, "row": row, "field": field, "message": message})

    seen_addresses: dict[str, int] = {}
    known_pids = set()
    for i, a in enumerate(data["addresses"], start=2):
        known_pids.add(a["property_id"])
        for field in ("address", "city", "state"):
            if not a[field]:
                add("ERROR", "addresses.csv", i, field, f"Missing {field}")
        if a["state"] and len(a["state"]) != 2:
            add("WARNING", "addresses.csv", i, "state", f"State '{a['state']}' is not a 2-letter code")
        key = f"{a['address']}|{a['city']}|{a['state']}".lower()
        if key in seen_addresses:
            add("ERROR", "addresses.csv", i, "address", f"Duplicate of row {seen_addresses[key]}")
        else:
            seen_addresses[key] = i
        if not a["price"]:
            add("ERROR", "addresses.csv", i, "price", "Missing price")
        else:
            try:
                if float(str(a["price"]).replace(",", "").replace("$", "")) <= 0:
                    add("WARNING", "addresses.csv", i, "price", "Price is zero or negative")
            except ValueError:
                add("ERROR", "addresses.csv", i, "price", f"Price '{a['price']}' is not numeric")
        if a["occupied"] == "":
            add("WARNING", "addresses.csv", i, "occupied", "Occupied value unrecognized/empty")

    occupied_pids = {a["property_id"] for a in data["addresses"] if a["occupied"] == "yes"}
    occupier_pids = set()
    for i, o in enumerate(data["occupier"], start=2):
        occupier_pids.add(o["property_id"])
        if o["property_id"] not in known_pids:
            add("ERROR", "occupier.csv", i, "property_id", "Occupier references unknown property")
        if not o["name"]:
            add("WARNING", "occupier.csv", i, "name", "Missing occupier name")
        if not o["email"]:
            add("ERROR", "occupier.csv", i, "email", "Missing occupier email")
        elif not EMAIL_RE.match(o["email"]):
            add("ERROR", "occupier.csv", i, "email", f"Email '{o['email']}' is not a valid address")
        digits = re.sub(r"\D", "", o["cell"] or "")
        if not o["cell"]:
            add("WARNING", "occupier.csv", i, "cell", "Missing cell number")
        elif len(digits) not in (10, 11):
            add("WARNING", "occupier.csv", i, "cell", f"Cell '{o['cell']}' does not look like a phone number")
    for pid in sorted(occupied_pids - occupier_pids):
        add("ERROR", "occupier.csv", 0, "property_id", f"Occupied property {pid} has no occupier record")

    utility_pids = set()
    for i, u in enumerate(data["utilities"], start=2):
        utility_pids.add(u["property_id"])
        if u["property_id"] not in known_pids:
            add("ERROR", "utilities.csv", i, "property_id", "Utility references unknown property")
        if not u["account_number"]:
            add("WARNING", "utilities.csv", i, "account_number", "Missing utility account number")
    for pid in sorted(known_pids - utility_pids):
        add("WARNING", "utilities.csv", 0, "property_id", f"Property {pid} has no utility record")
    return issues


def write_reports(migration_date: str, issues: list[dict], log) -> tuple[str, str]:
    base = mig_dir(migration_date)
    reports = os.path.join(base, "reports")
    os.makedirs(reports, exist_ok=True)
    errors = [i for i in issues if i["level"] == "ERROR"]
    warnings = [i for i in issues if i["level"] == "WARNING"]

    log_name = f"precheck-{migration_date}.log.txt"
    lines = [
        f"proj-manager pre-check (dry run) — migration {migration_date}",
        f"Generated {datetime.now(timezone.utc).isoformat()}",
        f"Errors: {len(errors)}  Warnings: {len(warnings)}",
        "",
    ]
    lines += [f"[{i['level']}] {i['file']} row {i['row']} field {i['field']}: {i['message']}" for i in issues]
    if not issues:
        lines.append("[INFO] No issues found.")
    with open(os.path.join(reports, log_name), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")

    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    ws.append(["Migration date", migration_date])
    ws.append(["Errors", len(errors)])
    ws.append(["Warnings", len(warnings)])
    ws.append(["Generated", datetime.now(timezone.utc).isoformat()])
    for title, rows in (("Errors", errors), ("Warnings", warnings)):
        sheet = wb.create_sheet(title)
        sheet.append(["File", "Row", "Field", "Message"])
        for r in rows:
            sheet.append([r["file"], r["row"], r["field"], r["message"]])
    combined = os.path.join(base, "combined")
    for fname, title in (("addresses.csv", "Addresses_Fixes"), ("occupier.csv", "Occupier_Fixes"), ("utilities.csv", "Utilities_Fixes")):
        sheet = wb.create_sheet(title)
        file_issues: dict[int, list[str]] = {}
        for i in issues:
            if i["file"] == fname and i["row"] > 0:
                file_issues.setdefault(i["row"], []).append(f"[{i['level']}] {i['field']}: {i['message']}")
        path = os.path.join(combined, fname)
        if os.path.isfile(path):
            with open(path, newline="", encoding="utf-8") as fh:
                rows = list(csv.reader(fh))
            if rows:
                sheet.append(rows[0] + ["Issues"])
                for n, row in enumerate(rows[1:], start=2):
                    if n in file_issues:
                        sheet.append(row + ["; ".join(file_issues[n])])
    xlsx_name = f"summary-{migration_date}.xlsx"
    wb.save(os.path.join(reports, xlsx_name))
    log(f"Reports written: {log_name} ({len(errors)} errors, {len(warnings)} warnings), {xlsx_name}.")
    return log_name, xlsx_name


def upload_results(migration_date: str, folder_url: str, log_name: str, xlsx_name: str, log) -> None:
    if not graph_client.configured:
        log("Demo mode: reports kept locally (no SharePoint upload).")
        return
    try:
        site = graph_client.resolve_site()
        drive_id = graph_client.site_default_drive_id(site["id"])
        reports = os.path.join(mig_dir(migration_date), "reports")
        for name in (log_name, xlsx_name):
            with open(os.path.join(reports, name), "rb") as fh:
                graph_client.upload_small_file(drive_id, f"{folder_url.strip('/')}/Results", name, fh.read())
        log("Reports uploaded to the SharePoint folder under Results/.")
    except Exception as exc:
        log(f"[WARNING] Report upload to SharePoint failed: {exc}")


def sharing_token(url: str) -> str:  # helper for future sharing-link resolution
    return base64.urlsafe_b64encode(url.encode()).decode().rstrip("=").replace("/", "_").replace("+", "-")


def run_pipeline_steps(run, steps: list[str], db_log) -> dict:
    """Execute requested steps against a PipelineRun row; returns counts."""
    counts = {"errors": 0, "warnings": 0}
    data = None
    if "stage" in steps:
        run.stage = "stage"
        stage(run.migration_date, run.folder_url, db_log)
    if "normalize" in steps or "precheck" in steps or "report" in steps:
        run.stage = "normalize"
        data = normalize(run.migration_date, db_log)
    if "precheck" in steps or "report" in steps:
        run.stage = "precheck"
        issues = precheck(data)
        counts["errors"] = sum(1 for i in issues if i["level"] == "ERROR")
        counts["warnings"] = sum(1 for i in issues if i["level"] == "WARNING")
        db_log(f"Pre-check complete: {counts['errors']} error(s), {counts['warnings']} warning(s).")
        if "report" in steps:
            run.stage = "report"
            log_name, xlsx_name = write_reports(run.migration_date, issues, db_log)
            run.log_artifact, run.xlsx_artifact = log_name, xlsx_name
            upload_results(run.migration_date, run.folder_url, log_name, xlsx_name, db_log)
    return counts
