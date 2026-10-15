"""SCART - egyfájlos Streamlit/GitHub átmeneti kiadás.

A teljes SCART alkalmazás és core logika egyetlen app.py fájlban.
Heti zárás: csütörtök 14:00 (Europe/Budapest).
"""

from __future__ import annotations

import copy
from collections import Counter
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import shutil
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
from filelock import FileLock, Timeout

SCART_NAME = "SCART"
SCART_VERSION = "1.0.6"
APP_TIMEZONE = ZoneInfo("Europe/Budapest")

DAILY_LABEL = "Napi adatok"
WEEKLY_LABEL = "Heti (Csütörtöki zárás 14:00)"
MONTHLY_LABEL = "Havi összesítés"
YEARLY_LABEL = "Éves összesítés"
LEGACY_WEEKLY_LABELS = {"Heti (Cs 14:00)", WEEKLY_LABEL}

PASSWORD_SCHEME = "pbkdf2_sha256"
PASSWORD_ITERATIONS = 600_000


class DataFileError(RuntimeError):
    """Raised when a SCART JSON data file cannot be safely loaded."""


class ConcurrentUpdateError(RuntimeError):
    """Raised when the database changed after the current view was loaded."""


def budapest_now() -> datetime:
    return datetime.now(APP_TIMEZONE)


def get_thursday_period_end(dt: Any) -> pd.Timestamp:
    """Return the Thursday 14:00 close that owns *dt*.

    Exact Thursday 14:00 belongs to the closing week. Any time after 14:00
    on Thursday belongs to the next weekly period.
    """
    ts = pd.Timestamp(dt)
    if ts.tzinfo is not None:
        ts = ts.tz_convert(APP_TIMEZONE).tz_localize(None)
    days_to_thursday = 3 - ts.weekday()
    close = ts.normalize() + pd.Timedelta(days=days_to_thursday, hours=14)
    if ts > close:
        close += pd.Timedelta(days=7)
    return close


def calculate_stat_condition(data, survival_line=0, inverted=False):
    """Classify recent movement, respecting lower-is-better (inverted) stats."""
    if not data:
        return "Nincs adat", "gray"

    try:
        valid = []
        for item in data:
            if not isinstance(item, (list, tuple)) or len(item) < 2:
                continue
            ts = pd.to_datetime(item[0], errors="coerce")
            val = pd.to_numeric(item[1], errors="coerce")
            if pd.isna(ts) or pd.isna(val):
                continue
            valid.append((ts, float(val)))

        if not valid:
            return "Nincs adat", "gray"

        valid.sort(key=lambda x: x[0])
        last_val = valid[-1][1]

        if survival_line and float(survival_line) > 0:
            threshold = float(survival_line)
            is_below_line = last_val < threshold
            is_danger = (not is_below_line) if inverted else is_below_line
            if is_danger:
                return "Nem-létezés (Életvonalon kívül)", "red"

        if len(valid) < 2:
            return "Nincs elegendő trendadat", "gray"

        vals = [v for _, v in valid[-4:]]
        if all(v == 0 for v in vals):
            return "Nem-létezés", "red"

        first_v, last_v = vals[0], vals[-1]
        diff = last_v - first_v
        effective_diff = -diff if inverted else diff

        if effective_diff > 0:
            base = abs(first_v) if abs(first_v) > 0 else 1.0
            growth_ratio = abs(diff) / base
            if growth_ratio >= 0.5:
                return "Bőség trend", "green"
            return "Normál trend", "green"
        if effective_diff == 0:
            return "Stagnáló trend", "orange"

        base = abs(first_v) if abs(first_v) > 0 else 1.0
        drop_ratio = abs(diff) / base
        if drop_ratio >= 0.3:
            return "Veszély trend", "red"
        return "Vészhelyzet trend", "orange"
    except Exception:
        return "Nincs adat", "gray"


def _password_hash_parts(encoded: str):
    parts = str(encoded).split("$", 3)
    if len(parts) != 4 or parts[0] != PASSWORD_SCHEME:
        return None
    try:
        iterations = int(parts[1])
    except ValueError:
        return None
    return iterations, parts[2], parts[3]


def hash_password(password: str, iterations: int = PASSWORD_ITERATIONS) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", str(password).encode("utf-8"), salt.encode("ascii"), iterations
    ).hex()
    return f"{PASSWORD_SCHEME}${iterations}${salt}${digest}"


def verify_password(password: str, encoded: str) -> bool:
    parsed = _password_hash_parts(encoded)
    if parsed is None:
        # Backward-compatible verification for one-time migration only.
        return hmac.compare_digest(str(password), str(encoded))
    iterations, salt, expected = parsed
    actual = hashlib.pbkdf2_hmac(
        "sha256", str(password).encode("utf-8"), salt.encode("ascii"), iterations
    ).hex()
    return hmac.compare_digest(actual, expected)


def password_is_hashed(encoded: str) -> bool:
    return _password_hash_parts(encoded) is not None


def _read_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def file_sha256(path: Path | str) -> str:
    path = Path(path)
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json_dump(path: Path | str, data: Any, create_backup: bool = True) -> None:
    """Write JSON atomically and keep the previous valid version as .bak."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())

        # Validate the temporary file before replacing the live file.
        _read_json(Path(tmp_name))

        if create_backup and path.exists():
            try:
                current = _read_json(path)
                if current is not None:
                    shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
            except Exception:
                # Never replace a known-good backup with a corrupt primary file.
                pass

        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def load_json_with_recovery(
    path: Path | str,
    *,
    default_if_missing: Any = None,
    required: bool = False,
):
    """Load JSON, restoring the most recent valid .bak if the primary is corrupt."""
    path = Path(path)
    backup = path.with_suffix(path.suffix + ".bak")

    if not path.exists():
        if backup.exists():
            try:
                data = _read_json(backup)
                shutil.copy2(backup, path)
                return data, f"{path.name}: a hiányzó főfájl a biztonsági mentésből helyreállítva."
            except Exception as exc:
                raise DataFileError(
                    f"A(z) {path.name} hiányzik, és a biztonsági mentés sem olvasható: {exc}"
                ) from exc
        if required:
            raise DataFileError(f"A kötelező adatfájl hiányzik: {path}")
        return copy.deepcopy(default_if_missing), None

    try:
        return _read_json(path), None
    except Exception as primary_exc:
        if backup.exists():
            try:
                data = _read_json(backup)
                stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                corrupt_copy = path.with_name(f"{path.name}.corrupt-{stamp}")
                shutil.copy2(path, corrupt_copy)
                shutil.copy2(backup, path)
                return data, (
                    f"{path.name}: sérült főfájl észlelve; a legutóbbi biztonsági "
                    f"mentés automatikusan helyreállítva. A sérült példány: {corrupt_copy.name}"
                )
            except Exception as backup_exc:
                raise DataFileError(
                    f"A(z) {path.name} és a .bak biztonsági mentése is hibás. "
                    f"Főfájl hiba: {primary_exc}; backup hiba: {backup_exc}"
                ) from backup_exc
        raise DataFileError(
            f"A(z) {path.name} sérült és nincs használható biztonsági mentés: {primary_exc}"
        ) from primary_exc


def normalize_database(db: Any) -> dict:
    if not isinstance(db, dict):
        raise DataFileError("A statisztikai adatbázis gyökéreleme nem objektum.")
    db = copy.deepcopy(db)
    db.setdefault("groups", [])
    db.setdefault("stats", {})
    db.setdefault("settings", {})
    if not isinstance(db.get("_meta"), dict):
        db["_meta"] = {}
    db["_meta"]["revision"] = int(db["_meta"].get("revision", 0) or 0)

    if not isinstance(db["groups"], list) or not isinstance(db["stats"], dict):
        raise DataFileError("A statisztikai adatbázis szerkezete hibás.")
    if not isinstance(db["settings"], dict):
        db["settings"] = {}

    # Migrate old weekly setting keys to the canonical label.
    for stat_name, settings in list(db["settings"].items()):
        if not isinstance(settings, dict):
            db["settings"][stat_name] = {}
            continue
        for old_key in LEGACY_WEEKLY_LABELS:
            if old_key != WEEKLY_LABEL and old_key in settings:
                if WEEKLY_LABEL not in settings:
                    settings[WEEKLY_LABEL] = settings[old_key]
                del settings[old_key]

    # Ensure data containers are sane without silently altering values.
    for stat_name, stat in list(db["stats"].items()):
        if not isinstance(stat, dict):
            raise DataFileError(f"Hibás statisztika objektum: {stat_name}")
        stat.setdefault("unit", "")
        stat.setdefault("group", "Egyéb")
        stat.setdefault("inverted", False)
        stat.setdefault("description", "")
        stat.setdefault("data", [])
        if not isinstance(stat["data"], list):
            raise DataFileError(f"A(z) '{stat_name}' adatsora nem lista.")
    return db


def load_database(path: Path | str):
    empty_db = {"groups": ["Egyéb"], "stats": {}, "settings": {}, "_meta": {"revision": 0}}
    raw, recovery = load_json_with_recovery(path, default_if_missing=empty_db)
    return normalize_database(raw), recovery


def save_database(path: Path | str, db: dict, timeout: float = 8.0) -> dict:
    """Optimistic + locked save: stale sessions can never silently overwrite newer data."""
    path = Path(path)
    lock = FileLock(str(path) + ".lock", timeout=timeout)
    try:
        with lock:
            latest_raw, _ = load_json_with_recovery(path, default_if_missing={
                "groups": ["Egyéb"], "stats": {}, "settings": {}, "_meta": {"revision": 0}
            })
            latest = normalize_database(latest_raw)
            ours = normalize_database(db)
            expected_revision = int(ours.get("_meta", {}).get("revision", 0))
            actual_revision = int(latest.get("_meta", {}).get("revision", 0))
            if path.exists() and actual_revision != expected_revision:
                raise ConcurrentUpdateError(
                    "Az adatbázist közben egy másik munkamenet módosította. "
                    "A mentést a SCART biztonsági okból nem írta rá a frissebb adatokra."
                )
            ours["_meta"]["revision"] = actual_revision + 1
            atomic_json_dump(path, ours, create_backup=True)
            return ours
    except Timeout as exc:
        raise DataFileError("Az adatfájl jelenleg zárolt; a mentés nem hajtható végre biztonságosan.") from exc


def normalize_users(users: Any) -> tuple[dict, bool]:
    if not isinstance(users, dict):
        raise DataFileError("A felhasználói adatbázis gyökéreleme nem objektum.")
    changed = False
    result = {}
    for username, value in users.items():
        if not isinstance(value, dict):
            # Legacy string format: value itself was the password.
            value = {
                "password": str(value),
                "role": "admin" if username == "admin" else "user",
                "assigned_stats": [],
                "assigned_groups": [],
            }
            changed = True
        else:
            value = copy.deepcopy(value)
        value.setdefault("role", "user")
        value.setdefault("assigned_stats", [])
        value.setdefault("assigned_groups", [])
        value.setdefault("auth_version", 1)
        if not password_is_hashed(value.get("password", "")):
            value["password"] = hash_password(value.get("password", ""))
            changed = True
        result[str(username)] = value
    return result, changed


def load_users_file(path: Path | str):
    path = Path(path)
    raw, recovery = load_json_with_recovery(path, required=True)
    users, changed = normalize_users(raw)
    return users, changed, recovery, file_sha256(path)


def save_users_file(
    path: Path | str,
    users: dict,
    timeout: float = 8.0,
    create_backup: bool = True,
    expected_digest: str | None = None,
) -> str:
    path = Path(path)
    lock = FileLock(str(path) + ".lock", timeout=timeout)
    try:
        with lock:
            if expected_digest is not None and path.exists():
                current_digest = file_sha256(path)
                if current_digest != expected_digest:
                    raise ConcurrentUpdateError(
                        "A felhasználói adatokat közben egy másik munkamenet módosította."
                    )
            atomic_json_dump(path, users, create_backup=create_backup)
            if not create_backup:
                # Password migration must not leave the former plaintext file in .bak.
                shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
            return file_sha256(path)
    except Timeout as exc:
        raise DataFileError("A felhasználói adatfájl jelenleg zárolt.") from exc


def load_archive_file(path: Path | str):
    path = Path(path)
    raw, recovery = load_json_with_recovery(path, default_if_missing={})
    if not isinstance(raw, dict):
        raise DataFileError("Az archívum formátuma hibás.")
    if not path.exists():
        atomic_json_dump(path, raw, create_backup=False)
    return raw, recovery, file_sha256(path)


def save_archive_file(
    path: Path | str,
    archive: dict,
    timeout: float = 8.0,
    expected_digest: str | None = None,
) -> str:
    path = Path(path)
    lock = FileLock(str(path) + ".lock", timeout=timeout)
    try:
        with lock:
            if expected_digest is not None and path.exists():
                current_digest = file_sha256(path)
                if current_digest != expected_digest:
                    raise ConcurrentUpdateError(
                        "Az archívumot közben egy másik munkamenet módosította."
                    )
            atomic_json_dump(path, archive, create_backup=True)
            return file_sha256(path)
    except Timeout as exc:
        raise DataFileError("Az archívum jelenleg zárolt.") from exc


def load_audit_file(path: Path | str):
    """Load the append-only SCART activity log."""
    path = Path(path)
    raw, recovery = load_json_with_recovery(path, default_if_missing=[])
    if not isinstance(raw, list):
        raise DataFileError("A tevékenységi napló formátuma hibás.")
    if not path.exists():
        atomic_json_dump(path, raw, create_backup=False)
    return raw, recovery


def append_audit_file(path: Path | str, event: dict, timeout: float = 8.0) -> None:
    """Append one audit event under a file lock and save atomically."""
    path = Path(path)
    lock = FileLock(str(path) + ".lock", timeout=timeout)
    try:
        with lock:
            raw, _ = load_json_with_recovery(path, default_if_missing=[])
            if not isinstance(raw, list):
                raise DataFileError("A tevékenységi napló formátuma hibás.")
            raw.append(copy.deepcopy(event))
            atomic_json_dump(path, raw, create_backup=True)
    except Timeout as exc:
        raise DataFileError("A tevékenységi napló jelenleg zárolt.") from exc


def _audit_row_diff(before_rows, after_rows):
    """Return multiset differences for SCART rows without requiring persistent row IDs."""
    def encode(row):
        return json.dumps(list(row), ensure_ascii=False, separators=(",", ":"), default=str)

    before_counter = Counter(encode(row) for row in before_rows)
    after_counter = Counter(encode(row) for row in after_rows)
    added = []
    removed = []
    for encoded, count in (after_counter - before_counter).items():
        added.extend([json.loads(encoded)] * count)
    for encoded, count in (before_counter - after_counter).items():
        removed.extend([json.loads(encoded)] * count)
    return added, removed


def validate_table_row(date_text: str, time_text: str, value: Any):
    full_dt = f"{date_text} {time_text}".strip()
    parsed = pd.to_datetime(full_dt, format="mixed", errors="coerce")
    numeric = pd.to_numeric(value, errors="coerce")
    errors = []
    if pd.isna(parsed):
        errors.append("hibás dátum/idő")
    if pd.isna(numeric):
        errors.append("hibás számérték")
    return parsed, numeric, errors


def _looks_like_time(value: Any) -> bool:
    """Return True for simple Excel-style time cells such as 14:00 or 14:00:30."""
    text = str(value).strip()
    parts = text.split(":")
    if len(parts) not in (2, 3):
        return False
    try:
        hour = int(parts[0])
        minute = int(parts[1])
        second = int(parts[2]) if len(parts) == 3 else 0
    except ValueError:
        return False
    return 0 <= hour <= 23 and 0 <= minute <= 59 and 0 <= second <= 59


def _parse_excel_number(value: Any):
    """Parse Hungarian/Excel numeric text, including spaces, Ft/db text and comma decimals."""
    raw = str(value).strip().replace("\xa0", " ").replace("−", "-")
    if not raw:
        return None

    # Keep only characters that can belong to a number. This also tolerates
    # cells copied as e.g. "1 250 000 Ft" or "1.250.000 Ft".
    clean = re.sub(r"[^0-9,.+-]", "", raw.replace(" ", ""))
    if not clean:
        return None

    if "," in clean and "." in clean:
        # Hungarian formatting: 1.234.567,89
        if clean.rfind(",") > clean.rfind("."):
            clean = clean.replace(".", "").replace(",", ".")
        else:
            # International formatting: 1,234,567.89
            clean = clean.replace(",", "")
    elif "," in clean:
        if clean.count(",") == 1:
            clean = clean.replace(",", ".")
        else:
            clean = clean.replace(",", "")
    elif clean.count(".") > 1:
        clean = clean.replace(".", "")
    elif clean.count(".") == 1:
        left, right = clean.split(".", 1)
        # In Hungarian Excel a single dot followed by three digits is usually
        # a thousands separator, e.g. 1.500 -> 1500.
        if left.lstrip("+-").isdigit() and right.isdigit() and len(right) == 3:
            clean = left + right

    try:
        return float(clean)
    except ValueError:
        return None


def _normalize_minicrm_header(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _parse_date_cell(value: Any):
    """Parse an Excel/clipboard date using Hungarian day-first conventions."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return pd.NaT
    if isinstance(value, (pd.Timestamp, datetime)):
        return pd.Timestamp(value)
    parsed = pd.to_datetime(value, format="mixed", dayfirst=True, errors="coerce")
    if pd.isna(parsed):
        parsed = pd.to_datetime(value, dayfirst=True, errors="coerce")
    return parsed


def _finish_minicrm_rows(date_value_pairs: list[tuple[Any, Any]], default_time):
    """Create one SCART row per calendar date from MiniCRM date/amount pairs."""
    daily_totals = {}
    skipped_no_date = 0
    skipped_bad_value = 0
    skipped_negative = 0

    for raw_date, raw_value in date_value_pairs:
        parsed_date = _parse_date_cell(raw_date)
        if pd.isna(parsed_date):
            skipped_no_date += 1
            continue

        numeric_value = _parse_excel_number(raw_value)
        if numeric_value is None:
            skipped_bad_value += 1
            continue
        # Negatív Fizetve tétel is lehet valós MiniCRM korrekció (például
        # E-helyesbítő számla), ezért azt nem dobjuk el.
        day_key = pd.Timestamp(parsed_date).normalize()
        daily_totals[day_key] = daily_totals.get(day_key, 0.0) + float(numeric_value)

    parsed_rows = []
    for day_key in sorted(daily_totals):
        ts = day_key + pd.Timedelta(
            hours=int(default_time.hour),
            minutes=int(default_time.minute),
            seconds=int(getattr(default_time, "second", 0)),
        )
        value_out = float(daily_totals[day_key])
        if value_out.is_integer():
            value_out = int(value_out)
        parsed_rows.append([ts.strftime("%Y-%m-%d %H:%M"), value_out, ""])

    stats = {
        "source_rows": len(date_value_pairs),
        "imported_dates": len(parsed_rows),
        "skipped_no_date": skipped_no_date,
        "skipped_bad_value": skipped_bad_value,
        "skipped_negative": skipped_negative,
    }
    return parsed_rows, stats


def _minicrm_effective_date(payment_value: Any, issue_value: Any):
    """Use payment date when present, otherwise fall back to invoice issue date."""
    payment_date = _parse_date_cell(payment_value)
    if pd.notna(payment_date):
        return payment_date, False
    issue_date = _parse_date_cell(issue_value)
    if pd.notna(issue_date):
        return issue_date, True
    return pd.NaT, False


def parse_minicrm_dataframe(df: pd.DataFrame, default_time):
    """Extract MiniCRM revenue data from the current invoice snapshot.

    Rules:
      * E-díjbekérő rows are never counted.
      * Only ``Fizetve`` invoices contribute to revenue.
      * ``Kiállítva``, ``Sztornózva`` and ``Sztornó`` are excluded.
      * If payment date is blank on an otherwise paid invoice, issue date is used.
      * Covered dates include excluded invoice rows as well, so re-importing a full
        MiniCRM export can remove an amount retroactively when an older invoice has
        since changed from Fizetve to Sztornózva.
    """
    if df is None or df.empty:
        return [], ["Az Excel nem tartalmaz feldolgozható sorokat."], {}

    header_map = {_normalize_minicrm_header(col): col for col in df.columns}
    payment_key = _normalize_minicrm_header("Számla: Kifizetés dátuma")
    issue_key = _normalize_minicrm_header("Számla: Kiállítás dátuma")
    amount_key = _normalize_minicrm_header("Számla: Nettó összeg")
    name_key = _normalize_minicrm_header("Adatlap: Név")
    status_key = _normalize_minicrm_header("Adatlap: Státusz")

    required = [amount_key, name_key, status_key]
    missing = [k for k in required if k not in header_map]
    if missing or (payment_key not in header_map and issue_key not in header_map):
        return [], [
            "A MiniCRM Excelből hiányzik valamelyik szükséges oszlop: "
            "'Adatlap: Név', 'Adatlap: Státusz', 'Számla: Nettó összeg', valamint "
            "legalább az egyik dátumoszlop (Kifizetés dátuma / Kiállítás dátuma)."
        ], {}

    name_col = header_map[name_key]
    status_col = header_map[status_key]
    amount_col = header_map[amount_key]
    payment_col = header_map.get(payment_key)
    issue_col = header_map.get(issue_key)

    pairs = []
    covered_dates = set()
    skipped_proforma = 0
    skipped_issued = 0
    skipped_cancelled_original = 0
    skipped_cancel_note = 0
    skipped_other_status = 0
    fallback_issue_date = 0
    skipped_no_date = 0

    for _, row in df.iterrows():
        name = str(row.get(name_col, "") or "").strip()
        status = str(row.get(status_col, "") or "").strip().casefold()
        payment_value = row.get(payment_col) if payment_col is not None else None
        issue_value = row.get(issue_col) if issue_col is not None else None
        effective_date, used_issue_fallback = _minicrm_effective_date(payment_value, issue_value)

        # Every usable invoice date is a date covered by this export. This is
        # important for retroactive correction: a formerly paid invoice may now
        # be Sztornózva, so the old aggregated SCART day must be recalculated.
        if pd.notna(effective_date):
            covered_dates.add(pd.Timestamp(effective_date).strftime("%Y-%m-%d"))

        if "díjbekérő" in name.casefold():
            skipped_proforma += 1
            continue

        if status == "kiállítva":
            skipped_issued += 1
            continue
        if status == "sztornózva":
            skipped_cancelled_original += 1
            continue
        if status == "sztornó":
            skipped_cancel_note += 1
            continue
        if status != "fizetve":
            skipped_other_status += 1
            continue

        if pd.isna(effective_date):
            skipped_no_date += 1
            continue
        if used_issue_fallback:
            fallback_issue_date += 1

        pairs.append((effective_date, row.get(amount_col)))

    rows, stats = _finish_minicrm_rows(pairs, default_time)
    # _finish_minicrm_rows only sees the accepted paid rows. Keep the broader
    # source-level counters separately.
    stats["covered_dates"] = sorted(covered_dates)
    stats["skipped_proforma"] = skipped_proforma
    stats["skipped_issued"] = skipped_issued
    stats["skipped_cancelled_original"] = skipped_cancelled_original
    stats["skipped_cancel_note"] = skipped_cancel_note
    stats["skipped_other_status"] = skipped_other_status
    stats["fallback_issue_date"] = fallback_issue_date
    stats["source_skipped_no_date"] = skipped_no_date
    return rows, [], stats

def parse_minicrm_excel_file(uploaded_file, default_time):
    """Read the first sheet of a MiniCRM .xlsx export and extract date + amount."""
    try:
        if hasattr(uploaded_file, "seek"):
            uploaded_file.seek(0)
        df = pd.read_excel(uploaded_file, sheet_name=0)
    except Exception as exc:
        return [], [f"A MiniCRM Excel nem olvasható: {exc}"], {}
    return parse_minicrm_dataframe(df, default_time)


def parse_excel_paste(pasted_text: str, default_time) -> tuple[list, list, dict]:
    """Parse rows copied from Excel, including the full MiniCRM export.

    MiniCRM mode is detected from the header. In that mode SCART imports paid
    invoices by date + net amount. Payment date is preferred; when it is blank,
    issue date is used. Pro-forma, Kiállítva, Sztornózva and Sztornó rows are
    excluded, and rows with the same effective date are summed.

    Simple layouts are still supported:
      Dátum | Érték
      Dátum | Érték | Megjegyzés
      Dátum | Időpont | Érték | Megjegyzés
    """
    raw_lines = [line for line in str(pasted_text or "").splitlines() if line.strip()]
    if not raw_lines:
        return [], [], {}

    first_cells = [cell.strip() for cell in raw_lines[0].split("\t")]
    if len(first_cells) == 1 and ";" in raw_lines[0]:
        first_cells = [cell.strip() for cell in raw_lines[0].split(";")]

    normalized_headers = [_normalize_minicrm_header(c) for c in first_cells]
    payment_header = _normalize_minicrm_header("Számla: Kifizetés dátuma")
    amount_header = _normalize_minicrm_header("Számla: Nettó összeg")

    # Full MiniCRM clipboard export. Use the same rules as the .xlsx importer.
    if payment_header in normalized_headers and amount_header in normalized_headers:
        issue_header = _normalize_minicrm_header("Számla: Kiállítás dátuma")
        name_header = _normalize_minicrm_header("Adatlap: Név")
        status_header = _normalize_minicrm_header("Adatlap: Státusz")

        if name_header not in normalized_headers or status_header not in normalized_headers:
            return [], [
                "A MiniCRM beillesztésből hiányzik az 'Adatlap: Név' vagy "
                "az 'Adatlap: Státusz' oszlop."
            ], {}

        date_idx = normalized_headers.index(payment_header)
        amount_idx = normalized_headers.index(amount_header)
        issue_idx = normalized_headers.index(issue_header) if issue_header in normalized_headers else None
        name_idx = normalized_headers.index(name_header)
        status_idx = normalized_headers.index(status_header)

        pairs = []
        malformed = []
        covered_dates = set()
        skipped_proforma = 0
        skipped_issued = 0
        skipped_cancelled_original = 0
        skipped_cancel_note = 0
        skipped_other_status = 0
        fallback_issue_date = 0
        source_skipped_no_date = 0

        for line_no, raw_line in enumerate(raw_lines[1:], start=2):
            cells = [cell.strip() for cell in raw_line.split("\t")]
            if len(cells) == 1 and ";" in raw_line:
                cells = [cell.strip() for cell in raw_line.split(";")]

            needed_indices = [date_idx, amount_idx, name_idx, status_idx]
            if issue_idx is not None:
                needed_indices.append(issue_idx)
            if max(needed_indices) >= len(cells):
                malformed.append(f"{line_no}. sor: hiányos MiniCRM sor")
                continue

            name = cells[name_idx]
            status = cells[status_idx].strip().casefold()
            payment_value = cells[date_idx]
            issue_value = cells[issue_idx] if issue_idx is not None else None
            effective_date, used_issue_fallback = _minicrm_effective_date(payment_value, issue_value)

            if pd.notna(effective_date):
                covered_dates.add(pd.Timestamp(effective_date).strftime("%Y-%m-%d"))

            if "díjbekérő" in name.casefold():
                skipped_proforma += 1
                continue
            if status == "kiállítva":
                skipped_issued += 1
                continue
            if status == "sztornózva":
                skipped_cancelled_original += 1
                continue
            if status == "sztornó":
                skipped_cancel_note += 1
                continue
            if status != "fizetve":
                skipped_other_status += 1
                continue

            if pd.isna(effective_date):
                source_skipped_no_date += 1
                continue
            if used_issue_fallback:
                fallback_issue_date += 1

            pairs.append((effective_date, cells[amount_idx]))

        rows, stats = _finish_minicrm_rows(pairs, default_time)
        stats["mode"] = "minicrm"
        stats["covered_dates"] = sorted(covered_dates)
        stats["skipped_proforma"] = skipped_proforma
        stats["skipped_issued"] = skipped_issued
        stats["skipped_cancelled_original"] = skipped_cancelled_original
        stats["skipped_cancel_note"] = skipped_cancel_note
        stats["skipped_other_status"] = skipped_other_status
        stats["fallback_issue_date"] = fallback_issue_date
        stats["source_skipped_no_date"] = source_skipped_no_date
        return rows, malformed, stats

    # Backward-compatible simple Excel paste mode.
    parsed_rows = []
    errors = []

    for line_no, raw_line in enumerate(raw_lines, start=1):
        cells = [cell.strip() for cell in raw_line.split("\t")]
        if len(cells) == 1 and ";" in raw_line:
            cells = [cell.strip() for cell in raw_line.split(";")]

        if line_no == 1:
            header = " ".join(cells).lower()
            has_date_header = any(k in header for k in ("dátum", "datum", "date"))
            has_value_header = any(k in header for k in ("érték", "ertek", "value", "összeg", "osszeg"))
            if has_date_header and has_value_header:
                continue

        if len(cells) < 2:
            errors.append(f"{line_no}. sor: legalább Dátum és Érték szükséges")
            continue

        date_cell = cells[0]
        time_cell = ""
        value_cell = ""
        note_cell = ""

        if len(cells) >= 3 and _looks_like_time(cells[1]):
            time_cell = cells[1]
            value_cell = cells[2]
            note_cell = " | ".join(c for c in cells[3:] if c)
        else:
            value_cell = cells[1]
            note_cell = " | ".join(c for c in cells[2:] if c)

        parsed_date = _parse_date_cell(date_cell)
        numeric_value = _parse_excel_number(value_cell)
        row_errors = []
        if pd.isna(parsed_date):
            row_errors.append("hibás dátum")
        if numeric_value is None:
            row_errors.append("hibás számérték")
        elif numeric_value < 0:
            row_errors.append("negatív érték")

        if row_errors:
            errors.append(f"{line_no}. sor: {', '.join(row_errors)}")
            continue

        ts = pd.Timestamp(parsed_date)
        if time_cell:
            time_parts = [int(part) for part in time_cell.split(":")]
            hour = time_parts[0]
            minute = time_parts[1]
            second = time_parts[2] if len(time_parts) == 3 else 0
            ts = ts.normalize() + pd.Timedelta(hours=hour, minutes=minute, seconds=second)
        elif ts.hour == 0 and ts.minute == 0 and ts.second == 0:
            ts = ts.normalize() + pd.Timedelta(
                hours=int(default_time.hour),
                minutes=int(default_time.minute),
                seconds=int(getattr(default_time, "second", 0)),
            )

        value_out = float(numeric_value)
        if value_out.is_integer():
            value_out = int(value_out)
        parsed_rows.append([ts.strftime("%Y-%m-%d %H:%M"), value_out, note_cell])

    return parsed_rows, errors, {"mode": "simple", "source_rows": len(parsed_rows)}


def _stat_data_sort_key(row):
    """Chronological sort key that safely pushes malformed legacy rows to the end."""
    try:
        ts = pd.to_datetime(str(row[0]), format="mixed", errors="coerce")
    except Exception:
        ts = pd.NaT
    if pd.isna(ts):
        return (1, pd.Timestamp.max)
    return (0, pd.Timestamp(ts))


# ================= SCART STREAMLIT FELÜLET =================
import copy
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components

# ================= OLDAL ALAPBEÁLLÍTÁSAI =================
st.set_page_config(
    page_title=SCART_NAME, layout="wide", page_icon="📊"
)

# ================= NYOMTATÁSI CSS =================
st.markdown(
    """
    <style>
    @media print {
        @page {
            size: A4 landscape;
            margin: 5mm !important;
        }
        [data-testid="stSidebar"], 
        [data-testid="stHeader"],
        [data-testid="stToolbar"],
        [data-baseweb="tab-list"],
        .stTabs [role="tablist"],
        .stForm, 
        button, 
        iframe,
        hr,
        h1, h2, h3, h4, h5, h6,
        [data-testid="stDataFrame"],
        [data-testid="stDataEditor"],
        .stElementContainer:not(:has(.stPlotlyChart)),
        .no-print {
            display: none !important;
        }
        [data-testid="stMainBlockContainer"] > div:not(:has(.stPlotlyChart)) {
            display: none !important;
        }
        html, body, [data-testid="stAppViewContainer"], .main, .block-container, [data-testid="stVerticalBlock"] {
            width: 100% !important;
            max-width: 100% !important;
            height: auto !important;
            margin: 0 !important;
            padding: 0 !important;
            background: white !important;
            overflow: visible !important;
        }
        .stPlotlyChart, .js-plotly-plot, .plot-container {
            width: 100% !important;
            max-width: 100% !important;
            margin: 0 auto !important;
            padding: 0 !important;
            page-break-inside: avoid !important;
        }
    }
    </style>
""",
    unsafe_allow_html=True,
)

# ================= ADATTÁROLÁS & FELHASZNÁLÓKEZELÉS =================
BASE_DIR = Path(__file__).resolve().parent
DB_FILE = BASE_DIR / "statisztikak.json"
ARCHIVE_FILE = BASE_DIR / "archivum.json"
USERS_FILE = BASE_DIR / "users.json"
AUDIT_FILE = BASE_DIR / "tevekenysegi_naplo.json"
RECOVERY_MESSAGES = []

# ================= EGYFÁJLOS GITHUB/STREAMLIT BOOTSTRAP =================
# A SCART főprogramja ebben az egy app.py fájlban van. Ha az adatfájlok nem
# léteznek (első indítás), az alábbi beágyazott kezdőállapotból létrejönnek.
# FIGYELEM: Streamlit Community Cloudon a helyi fájlrendszer nem tartós
# adatbázis; újraindítás/újratelepítés után a futás közben létrehozott fájlok
# elveszhetnek. Átmeneti használatra ezért rendszeres export/backup szükséges.

INITIAL_USERS = {'admin': {'password': 'pbkdf2_sha256$600000$14d3a3c4a3d422f517d6ea5250f84412$48e4b7a248b4e920f9969b4c80c706b28a813f0e5377c7f07ba2664ea230d349',
           'role': 'admin',
           'assigned_stats': [],
           'assigned_groups': [],
           'auth_version': 1},
 'laura': {'password': 'pbkdf2_sha256$600000$5d566b8937e4b6b39c2566bcfff4239d$016e33c27d96a9f8185811335b6551722a65633c1b9f3b47b0e750877ee7aa1f',
           'role': 'user',
           'assigned_stats': [],
           'assigned_groups': ['Pénzügy'],
           'auth_version': 1}}
INITIAL_DATABASE = {'groups': ['Pénzügy', 'Értékesítés', 'Marketing', 'Adminisztráció'],
 'stats': {'Bruttó Beérkezett Bevétel': {'unit': 'Ft',
                                         'group': 'Pénzügy',
                                         'inverted': False,
                                         'description': 'Az adott időszakban a bankszámlára '
                                                        'beérkezett bruttó összegek '
                                                        'kötelezettségek és jóváírások alapján.',
                                         'data': [['2026-01-09 14:00',
                                                   2670000,
                                                   'HTM PÉKSÉG 2026-E/00003'],
                                                  ['2026-01-10 14:00',
                                                   700000,
                                                   'ÉLETKERT 2026-E/00004'],
                                                  ['2026-01-15 09:03',
                                                   2138706,
                                                   'ALBA NÖVSZER 2026-E/00005'],
                                                  ['2026-01-15 16:00',
                                                   2040000,
                                                   'BEST ROYAL 2026-E/00007, 2026-E/00008'],
                                                  ['2026-01-15 17:55',
                                                   1250000,
                                                   'HORVÁTH ÉS TÁRSA 2026-E/00009'],
                                                  ['2026-01-15 18:19',
                                                   450000,
                                                   'FAIR-KÚT 2026-E/00006'],
                                                  ['2026-01-16 18:06',
                                                   85400,
                                                   'PIZZAMŰVEK DK2026-E/00002'],
                                                  ['2026-01-16 18:07',
                                                   85400,
                                                   'TRUE-AIM DK2026-E/00003'],
                                                  ['2026-01-26 18:17',
                                                   2000000,
                                                   'SÁNDORFI 2026-E/00013'],
                                                  ['2026-01-26 18:18',
                                                   250000,
                                                   'SÁNDORFI 2026-E/00014'],
                                                  ['2026-01-28 18:08',
                                                   85400,
                                                   'M-DOPEN DK2026-E/00016'],
                                                  ['2026-01-28 18:09',
                                                   145000,
                                                   'M-DOPEN DK2026-E/00006'],
                                                  ['2026-01-30 18:11',
                                                   135000,
                                                   'SZÍNVONAL DK2026-E/00007'],
                                                  ['2026-01-30 18:13',
                                                   85400,
                                                   'NORDOM SOLUTIONS 2026-E/00005'],
                                                  ['2026-01-30 18:21',
                                                   125000,
                                                   'RONION DK-2026-E/00008'],
                                                  ['2026-02-03 14:00',
                                                   15000000,
                                                   'SZÍNVONAL 2026-E/00022 (Előlegsz.)'],
                                                  ['2026-02-03 18:45',
                                                   960000,
                                                   'BRINGABOARD 2026-E/00015'],
                                                  ['2026-02-04 14:00',
                                                   803703,
                                                   'GAG MANAGEMENT 2026-E/00025'],
                                                  ['2026-02-05 18:35',
                                                   87850,
                                                   'FAIRCRAFT DK2026-E/00011'],
                                                  ['2026-02-11 18:36',
                                                   85400,
                                                   'TÚRA EGER DK2026-E/00010'],
                                                  ['2026-02-11 18:36',
                                                   87750,
                                                   'B&B HARD DK2026-E/00013'],
                                                  ['2026-02-13 18:37',
                                                   85400,
                                                   'BARADSLA DK2026-E/00009'],
                                                  ['2026-02-16 15:21',
                                                   255000,
                                                   'M-DOPEN 2026-E/00029'],
                                                  ['2026-02-16 18:38',
                                                   87750,
                                                   'FAIR-KÚT DK2026-E/00016'],
                                                  ['2026-02-17 18:38',
                                                   87500,
                                                   'M-DOPEN DK2026-E/00015'],
                                                  ['2026-02-18 18:39',
                                                   87750,
                                                   'W-R HUNGARY DK2026-E/00017'],
                                                  ['2026-02-19 18:40',
                                                   87750,
                                                   'MY CARPETDK2026-E/00018'],
                                                  ['2026-02-25 18:41',
                                                   75200,
                                                   'PLUMBER-BAU DK2026-E/00014'],
                                                  ['2026-02-26 18:42',
                                                   92400,
                                                   'V.I.P. DK2026-E/00019'],
                                                  ['2026-03-09 14:00',
                                                   680000,
                                                   'GYÖRÖKGÉP 2026-E/00040'],
                                                  ['2026-03-10 14:00',
                                                   1300000,
                                                   'AKÁC-CENTRUM 2026-E/00039'],
                                                  ['2026-03-16 18:52',
                                                   175420,
                                                   'FAIR-KÚT DK2026-E/00023'],
                                                  ['2026-03-17 18:56',
                                                   87750,
                                                   'THREE STONES DK2026-E/00021'],
                                                  ['2026-03-18 18:59',
                                                   175000,
                                                   'JÁRCSICS THERM DK2026-E/00026'],
                                                  ['2026-03-20 19:00',
                                                   900000,
                                                   'NORDOM SOLUTIONS 2026-E/00045'],
                                                  ['2026-03-23 19:01',
                                                   97600,
                                                   'MARKETING SZABÓSÁG DK2026-E/00029'],
                                                  ['2026-03-26 19:01',
                                                   175200,
                                                   'ENERGREEN KFT. DK2026-E/00030'],
                                                  ['2026-03-31 14:00',
                                                   87750,
                                                   'PAP GÁBOR (???) DK2026-E/00032'],
                                                  ['2026-03-31 18:51',
                                                   97600,
                                                   'B&T BUILD DK2026-E/00033'],
                                                  ['2026-03-31 19:03',
                                                   97600,
                                                   'PETTERN DK2026-E/00034'],
                                                  ['2026-04-08 14:00', 3000000, ''],
                                                  ['2026-04-21 14:00', 630000, ''],
                                                  ['2026-04-27 14:00', 355000, ''],
                                                  ['2026-05-04 14:00', 900000, ''],
                                                  ['2026-05-07 14:00', 1740000, ''],
                                                  ['2026-05-21 14:00', 4605000, ''],
                                                  ['2026-06-03 14:00', 2500000, ''],
                                                  ['2026-06-04 14:00', 1855000, ''],
                                                  ['2026-06-11 14:00', 255000, ''],
                                                  ['2026-06-18 14:00', 2260000, ''],
                                                  ['2026-06-26 14:00', 2311000, ''],
                                                  ['2026-06-29 14:00', 462998, ''],
                                                  ['2026-07-14 14:00', 1200000, ''],
                                                  ['2026-07-16 14:00', 857100, ''],
                                                  ['2026-07-23 14:00', 650000, 'Nyitó kampány'],
                                                  ['2026-07-30 14:00', 97500, ''],
                                                  ['2026-08-06 14:00', 97500, ''],
                                                  ['2026-08-11 14:00', 255000, ''],
                                                  ['2026-08-13 14:00',
                                                   547500,
                                                   'Új ügyfél szerződés'],
                                                  ['2026-08-19 14:00', 255000, ''],
                                                  ['2026-08-20 14:00', 347500, ''],
                                                  ['2026-08-24 14:00', 833299, ''],
                                                  ['2026-08-27 14:00', 635000, ''],
                                                  ['2026-09-02 14:00', 1800000, ''],
                                                  ['2026-09-03 14:00', 2350000, 'Prémium csomagok'],
                                                  ['2026-09-10 14:00', 390000, ''],
                                                  ['2026-09-16 14:00', 4606000, ''],
                                                  ['2026-09-17 14:00', 4722200, 'Rekord bevétel'],
                                                  ['2026-09-24 14:00', 0, 'Ünnepnap / leállás'],
                                                  ['2026-10-01 14:00', 750000, ''],
                                                  ['2026-10-06 14:00', 657000, ''],
                                                  ['2026-10-09 14:00', 3850000, ''],
                                                  ['2026-10-11 15:42', 97500, ''],
                                                  ['2026-10-13 14:00', 255000, ''],
                                                  ['2026-10-14 14:00', 255000, '']]},
           'Ügyfelek száma': {'unit': 'fő',
                              'group': 'Értékesítés',
                              'inverted': False,
                              'description': 'Az aktív szerződéssel rendelkező új és visszatérő '
                                             'ügyfelek száma.',
                              'data': [['2026-08-08 14:00', 5, 'Első körös hívások'],
                                       ['2026-08-15 14:00', 12, ''],
                                       ['2026-08-25 14:00', 18, 'Ajánlások'],
                                       ['2026-08-30 14:00', 25, ''],
                                       ['2026-09-13 14:00', 34, 'Marketing akció']]}},
 'settings': {},
 '_meta': {'revision': 0}}
INITIAL_ARCHIVE = {}

def _create_v105_upgrade_safety_snapshot():
    """Keep a one-time untouched copy of existing local data before v1.0.5 edits it."""
    snapshots = [
        (DB_FILE, BASE_DIR / "statisztikak.before_v1_0_5.json"),
        (ARCHIVE_FILE, BASE_DIR / "archivum.before_v1_0_5.json"),
        (USERS_FILE, BASE_DIR / "users.before_v1_0_5.json"),
    ]
    for source, snapshot in snapshots:
        if source.exists() and not snapshot.exists():
            try:
                shutil.copy2(source, snapshot)
            except Exception:
                # A snapshot extra védelem; emiatt az alkalmazás nem állhat le.
                pass


def _bootstrap_local_data_files():
    if not USERS_FILE.exists():
        atomic_json_dump(USERS_FILE, INITIAL_USERS, create_backup=False)
    if not DB_FILE.exists():
        atomic_json_dump(DB_FILE, INITIAL_DATABASE, create_backup=False)
    if not ARCHIVE_FILE.exists():
        atomic_json_dump(ARCHIVE_FILE, INITIAL_ARCHIVE, create_backup=False)


_create_v105_upgrade_safety_snapshot()
_bootstrap_local_data_files()


def _record_recovery(message):
    if message and message not in RECOVERY_MESSAGES:
        RECOVERY_MESSAGES.append(message)


def load_users():
    try:
        users, migrated, recovery, digest = load_users_file(USERS_FILE)
        _record_recovery(recovery)
        if migrated:
            digest = save_users_file(
                USERS_FILE, users, create_backup=False, expected_digest=digest
            )
        st.session_state["_users_digest"] = digest
        return users
    except DataFileError as exc:
        st.error(f"A SCART nem tudta biztonságosan betölteni a felhasználókat: {exc}")
        st.stop()


def save_users(users_dict):
    try:
        st.session_state["_users_digest"] = save_users_file(
            USERS_FILE,
            users_dict,
            expected_digest=st.session_state.get("_users_digest"),
        )
    except ConcurrentUpdateError as exc:
        st.session_state["_scart_flash_warning"] = (
            f"⚠️ {exc} A frissebb felhasználói adatokat újratöltöm; ismételd meg a módosítást."
        )
        st.rerun()
    except DataFileError as exc:
        st.error(f"A felhasználói adatok mentése sikertelen: {exc}")
        st.stop()


def fmt_num(val, unit=""):
    if val is None:
        return ""
    try:
        f_val = float(val)
        if f_val.is_integer():
            s = f"{int(f_val):,}".replace(",", ".")
        else:
            s = f"{f_val}".replace(",", ".")
    except (ValueError, TypeError):
        s = str(val)

    if unit:
        clean_unit = str(unit).strip(".")
        return f"{s} {clean_unit}"
    return s


def load_data():
    try:
        loaded, recovery = load_database(DB_FILE)
        _record_recovery(recovery)
        return loaded
    except DataFileError as exc:
        st.error(f"A SCART adatbázisa nem tölthető be biztonságosan: {exc}")
        st.info("A rendszer nem írja felül a hibás adatfájlt. Ellenőrizd a .bak mentést vagy a hibaüzenetet.")
        st.stop()


def save_data(db):
    try:
        saved = save_database(DB_FILE, db)
        db.clear()
        db.update(saved)
        st.session_state.db = db
        return True
    except ConcurrentUpdateError as exc:
        fresh, recovery = load_database(DB_FILE)
        _record_recovery(recovery)
        st.session_state.db = fresh
        st.session_state["_scart_flash_warning"] = (
            f"⚠️ {exc} A frissebb adatokat újratöltöttem; kérlek, ismételd meg az előző mentést."
        )
        st.rerun()
    except DataFileError as exc:
        st.error(f"A SCART mentése sikertelen: {exc}")
        st.stop()


def load_archive():
    try:
        archive, recovery, digest = load_archive_file(ARCHIVE_FILE)
        _record_recovery(recovery)
        st.session_state["_archive_digest"] = digest
        return archive
    except DataFileError as exc:
        st.error(f"Az archívum nem tölthető be biztonságosan: {exc}")
        st.stop()


def save_archive(archive_data):
    try:
        st.session_state["_archive_digest"] = save_archive_file(
            ARCHIVE_FILE,
            archive_data,
            expected_digest=st.session_state.get("_archive_digest"),
        )
    except ConcurrentUpdateError as exc:
        st.session_state["_scart_flash_warning"] = (
            f"⚠️ {exc} A frissebb archívumot újratöltöm; ismételd meg a műveletet."
        )
        st.rerun()
    except DataFileError as exc:
        st.error(f"Az archívum mentése sikertelen: {exc}")
        st.stop()


# Segédfüggvény a statisztika nevének és egységének megjelenítéséhez
def load_audit():
    try:
        audit_rows, recovery = load_audit_file(AUDIT_FILE)
        _record_recovery(recovery)
        return audit_rows
    except DataFileError as exc:
        st.error(f"A tevékenységi napló nem tölthető be biztonságosan: {exc}")
        st.stop()


def append_audit_event(
    action: str,
    *,
    stat_name: str = "",
    summary: str = "",
    details: Any = None,
    actor: str | None = None,
    actor_role: str | None = None,
) -> None:
    """Write a non-editable audit entry. Audit failure never destroys the business save."""
    username = actor if actor is not None else st.session_state.get("username", "")
    role = actor_role if actor_role is not None else st.session_state.get("user_role", "")
    event = {
        "id": secrets.token_hex(12),
        "timestamp": budapest_now().isoformat(timespec="seconds"),
        "user": username or "(ismeretlen)",
        "role": role or "",
        "action": str(action),
        "stat": str(stat_name or ""),
        "summary": str(summary or ""),
        "details": copy.deepcopy(details) if details is not None else {},
    }
    try:
        append_audit_file(AUDIT_FILE, event)
    except Exception as exc:
        # Az üzleti adat mentése ettől még sikeres marad, de az admin figyelmeztetést kap.
        st.session_state["_scart_audit_warning"] = (
            f"⚠️ Az adat mentése sikerült, de a tevékenységi napló írása nem: {exc}"
        )


def _audit_summary_from_rows(added_rows, removed_rows):
    parts = []
    if added_rows:
        parts.append(f"{len(added_rows)} sor hozzáadva/módosítva")
    if removed_rows:
        parts.append(f"{len(removed_rows)} korábbi sor törölve/módosítva")
    return "; ".join(parts) if parts else "Nincs sorváltozás"


def stat_label(stat_name):
    u = db["stats"].get(stat_name, {}).get("unit", "")
    if u:
        return f"{stat_name} ({u})"
    return stat_name


# ================= BEJELENTKEZÉSI LOGIKA =================
users_db = load_users()

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "username" not in st.session_state:
    st.session_state.username = ""
if "user_role" not in st.session_state:
    st.session_state.user_role = "user"
if "assigned_stats" not in st.session_state:
    st.session_state.assigned_stats = []
if "assigned_groups" not in st.session_state:
    st.session_state.assigned_groups = []
if "auth_version" not in st.session_state:
    st.session_state.auth_version = None

# A jogosultságok minden Streamlit újrafutáskor a friss users.json alapján érvényesülnek.
if st.session_state.logged_in:
    current_user = users_db.get(st.session_state.username)
    if current_user is None:
        st.session_state.logged_in = False
        st.session_state.username = ""
        st.session_state.auth_version = None
    else:
        current_auth_version = int(current_user.get("auth_version", 1))
        if st.session_state.auth_version is None:
            st.session_state.auth_version = current_auth_version
        elif int(st.session_state.auth_version) != current_auth_version:
            st.session_state.logged_in = False
            st.session_state.username = ""
            st.session_state.user_role = "user"
            st.session_state.assigned_stats = []
            st.session_state.assigned_groups = []
            st.session_state.auth_version = None
            st.warning("A jogosultságaid vagy a belépési adataid megváltoztak. Jelentkezz be újra.")
        if st.session_state.logged_in:
            st.session_state.user_role = current_user.get("role", "user")
            st.session_state.assigned_stats = current_user.get("assigned_stats", [])
            st.session_state.assigned_groups = current_user.get("assigned_groups", [])

if not st.session_state.logged_in:
    st.title("SCART – Bejelentkezés")
    with st.form("login_form"):
        input_user = st.text_input("Felhasználónév:")
        input_pass = st.text_input("Jelszó:", type="password")
        login_btn = st.form_submit_button("Bejelentkezés")

        if login_btn:
            if (
                input_user in users_db
                and verify_password(input_pass, users_db[input_user].get("password", ""))
            ):
                st.session_state.logged_in = True
                st.session_state.username = input_user
                st.session_state.user_role = users_db[input_user].get("role", "user")
                st.session_state.assigned_stats = users_db[input_user].get(
                    "assigned_stats", []
                )
                st.session_state.assigned_groups = users_db[input_user].get(
                    "assigned_groups", []
                )
                st.session_state.auth_version = int(users_db[input_user].get("auth_version", 1))
                append_audit_event(
                    "Bejelentkezés",
                    summary="Sikeres bejelentkezés",
                    actor=input_user,
                    actor_role=users_db[input_user].get("role", "user"),
                )
                st.success("Sikeres bejelentkezés!")
                st.rerun()
            else:
                append_audit_event(
                    "Sikertelen bejelentkezés",
                    summary="Hibás felhasználónév vagy jelszó",
                    actor=input_user or "(üres felhasználónév)",
                    actor_role="",
                )
                st.error("Hibás felhasználónév vagy jelszó!")

    st.stop()

# ================= SESSION STATE ADATOK =================
# Minden interakció friss adatbázisból indul. Ez megszünteti a hosszú életű,
# elavult session-másolatokból eredő felülírások döntő részét.
st.session_state.db = load_data()
db = st.session_state.db

# Ha egy statisztika olyan csoportba tartozik, amely nincs a listában,
# a csoport automatikusan bekerül, így nem marad "árva" kategória.
known_groups = list(db.get("groups", []))
for stat_obj in db.get("stats", {}).values():
    stat_group_name = stat_obj.get("group", "Egyéb") or "Egyéb"
    if stat_group_name not in known_groups:
        known_groups.append(stat_group_name)
if known_groups != db.get("groups", []):
    db["groups"] = known_groups
    save_data(db)

all_stat_names = list(db["stats"].keys())
all_groups = db.get("groups", [])

for recovery_message in RECOVERY_MESSAGES:
    st.warning(f"🛟 SCART helyreállítás: {recovery_message}")

if "_scart_flash_warning" in st.session_state:
    st.warning(st.session_state.pop("_scart_flash_warning"))
if "_scart_audit_warning" in st.session_state:
    st.warning(st.session_state.pop("_scart_audit_warning"))

# JOGOSULTSÁG ALAPJÁN ELÉRHETŐ STATISZTIKÁK SZŰRÉSE
if st.session_state.user_role == "admin":
    stat_names = all_stat_names
else:
    user_assigned_s = set(st.session_state.assigned_stats)
    user_assigned_g = set(st.session_state.assigned_groups)

    stat_names = []
    for s in all_stat_names:
        s_group = db["stats"][s].get("group", "Egyéb")
        if s in user_assigned_s or s_group in user_assigned_g:
            stat_names.append(s)

# ================= NAVIGÁCIÓ =================
st.sidebar.title("📊 SCART")
st.sidebar.caption(f"v{SCART_VERSION} · heti zárás: csütörtök 14:00")
st.sidebar.subheader("📌 Navigáció")
role_label = (
    "👑 Adminisztrátor"
    if st.session_state.user_role == "admin"
    else "👤 Sima Felhasználó"
)
st.sidebar.write(f"Bejelentkezve: **{st.session_state.username}**")
st.sidebar.caption(f"Jogosultság: {role_label}")

if st.sidebar.button("🚪 Kijelentkezés"):
    append_audit_event("Kijelentkezés", summary="Felhasználó kijelentkezett")
    st.session_state.logged_in = False
    st.session_state.username = ""
    st.session_state.user_role = "user"
    st.session_state.assigned_stats = []
    st.session_state.assigned_groups = []
    st.session_state.auth_version = None
    st.rerun()

st.sidebar.markdown("---")

menu_options = [
    "📊 Egyedi Statisztika Nézet",
    "📈 Több Statisztika Összevetése",
    "📋 Összesítő Dashboard (Kártya Nézet)",
]

if st.session_state.user_role == "admin":
    menu_options.extend(
        [
            "➕ Új Statisztika Létrehozása",
            "📖 Tevékenységi napló",
            "💾 Biztonsági mentés",
            "⚙️ Adminisztráció & Archívum",
        ]
    )

selected_menu = st.sidebar.radio("Válassz funkciót:", menu_options)
st.sidebar.markdown("---")

# ================= MODULOK =================

# 1. EGYEDI STATISZTIKA NÉZET
if selected_menu == "📊 Egyedi Statisztika Nézet":
    if not stat_names:
        st.warning(
            "⚠️ Nincs számodra elérhető statisztika hozzárendelve. Kérj hozzáférést"
            " az admintól!"
        )
    else:
        selected_stat = st.sidebar.selectbox(
            "Választott statisztika:", stat_names, format_func=stat_label
        )

        current_unit = db["stats"][selected_stat].get("unit", "")
        stat_group = db["stats"][selected_stat].get("group", "Egyéb")
        stat_settings = db.get("settings", {}).get(selected_stat, {})
        is_inverted = db["stats"][selected_stat].get("inverted", False)
        stat_desc = db["stats"][selected_stat].get("description", "")
        apply_all_requested = False
        original_stat_settings = copy.deepcopy(stat_settings)
        original_inverted = is_inverted

        if st.session_state.user_role == "admin":
            person_name = st.sidebar.text_input(
                "Név (Fejlécbe):",
                value=stat_settings.get("person_name", "Bíró Laura"),
                key=f"pname_{selected_stat}",
            )
            person_post = st.sidebar.text_input(
                "Poszt (Fejlécbe):",
                value=stat_settings.get("person_post", "DIV1"),
                key=f"ppost_{selected_stat}",
            )
            is_stat_inverted_check = st.sidebar.checkbox(
                "Fordított statisztika (0 felül van)",
                value=is_inverted,
                key=f"inv_{selected_stat}",
            )

            st.sidebar.markdown("---")
            st.sidebar.subheader("📐 Grafikon & Nyomtatás Méretezése")
            chart_height = st.sidebar.slider(
                "Grafikon magassága (px):",
                min_value=300,
                max_value=900,
                value=int(stat_settings.get("chart_height", 550)),
                step=10,
                key=f"ch_{selected_stat}",
            )

            col_m1, col_m2 = st.sidebar.columns(2)
            with col_m1:
                margin_l = st.number_input(
                    "Bal margó (px):",
                    value=int(stat_settings.get("margin_l", 60)),
                    step=5,
                    key=f"ml_{selected_stat}",
                )
                margin_t = st.number_input(
                    "Felső margó (px):",
                    value=int(stat_settings.get("margin_t", 130)),
                    step=5,
                    key=f"mt_{selected_stat}",
                )
            with col_m2:
                margin_r = st.number_input(
                    "Jobb margó (px):",
                    value=int(stat_settings.get("margin_r", 100)),
                    step=5,
                    key=f"mr_{selected_stat}",
                )
                margin_b = st.number_input(
                    "Alsó margó (px):",
                    value=int(stat_settings.get("margin_b", 90)),
                    step=5,
                    key=f"mb_{selected_stat}",
                )

            # --- BEÁLLÍTÁSOK ÁTVITELE MINDEN STATISZTIKÁRA GOMB ---
            # A tényleges másolás csak az összes aktuális widgetérték összeállítása után történik,
            # így nem a korábbi, lemezen tárolt beállítások kerülnek átmásolásra.
            st.sidebar.markdown("---")
            if st.sidebar.button(
                "🔄 Beállítások átvitele MINDEN statisztikára",
                key=f"apply_all_btn_{selected_stat}",
            ):
                apply_all_requested = True
        else:
            person_name = stat_settings.get("person_name", "Bíró Laura")
            person_post = stat_settings.get("person_post", "DIV1")
            is_stat_inverted_check = is_inverted
            chart_height = int(stat_settings.get("chart_height", 550))
            margin_l = int(stat_settings.get("margin_l", 60))
            margin_r = int(stat_settings.get("margin_r", 100))
            margin_t = int(stat_settings.get("margin_t", 130))
            margin_b = int(stat_settings.get("margin_b", 90))

        st.sidebar.markdown("---")
        st.sidebar.subheader("📅 Időszakos összesítés")
        valid_aggs = [DAILY_LABEL, WEEKLY_LABEL, MONTHLY_LABEL]
        indiv_agg = st.sidebar.selectbox(
            "Grafikon nézet:", valid_aggs, key=f"indiv_agg_view_{selected_stat}"
        )

        # --- ADATTÁBLA HÓNAP SZŰKÍTÉS ---
        # Ez kizárólag az alsó szerkeszthető adattáblát szűri. A teljes adatbázis
        # érintetlen marad, így egy hónap szerkesztése soha nem törli a többi hónapot.
        stat_rows_for_month_default = db["stats"][selected_stat].get("data", [])
        latest_valid_table_date = None
        for _row in reversed(sorted(stat_rows_for_month_default, key=_stat_data_sort_key)):
            if not isinstance(_row, (list, tuple)) or not _row:
                continue
            _ts = pd.to_datetime(str(_row[0]), format="mixed", errors="coerce")
            if pd.notna(_ts):
                latest_valid_table_date = pd.Timestamp(_ts).date()
                break
        if latest_valid_table_date is None:
            latest_valid_table_date = budapest_now().date()

        st.sidebar.markdown("---")
        st.sidebar.subheader("🗓️ Adattábla hónap szűkítés")
        table_show_all_months = st.sidebar.checkbox(
            "Összes hónap megjelenítése",
            value=False,
            key=f"table_show_all_months_{selected_stat}",
        )
        table_month_date = st.sidebar.date_input(
            "Melyik hónapot mutassa a táblázat?",
            value=latest_valid_table_date,
            key=f"table_month_date_{selected_stat}",
            disabled=table_show_all_months,
        )
        table_month_key = (
            None
            if table_show_all_months
            else f"{table_month_date.year:04d}-{table_month_date.month:02d}"
        )
        if table_month_key:
            st.sidebar.caption(
                f"Az alsó táblázat csak a(z) {table_month_date.year}. "
                f"{table_month_date.month:02d}. havi sorokat mutatja."
            )
        else:
            st.sidebar.caption("Az alsó táblázat minden rögzített sort mutat.")
        st.sidebar.caption("✍️ A táblázat módosításai automatikusan mentődnek.")

        mode_settings = stat_settings.get(indiv_agg, {})
        valid_goals = ["Nincs", "Fix érték (db/Ft)"]
        valid_chart_types = ["Vonaldiagram", "Oszlopdiagram (Bar)"]

        if st.session_state.user_role == "admin":
            st.sidebar.markdown("---")
            st.sidebar.subheader(f"📊 Diagram Típusa ({indiv_agg})")
            chart_type_val = mode_settings.get("chart_type", "Vonaldiagram")
            chart_type = st.sidebar.selectbox(
                "Diagram formátuma:",
                valid_chart_types,
                index=valid_chart_types.index(chart_type_val)
                if chart_type_val in valid_chart_types
                else 0,
                key=f"chart_type_{selected_stat}_{indiv_agg}",
            )

            st.sidebar.markdown("---")
            st.sidebar.subheader(f"📐 Skála Tengely Beállítások ({indiv_agg})")
            col_min, col_max, col_step = st.sidebar.columns(3)
            with col_min:
                ymin = st.text_input(
                    "Min",
                    value=str(mode_settings.get("ymin", "")),
                    key=f"ymin_{selected_stat}_{indiv_agg}",
                )
            with col_max:
                ymax = st.text_input(
                    "Max",
                    value=str(mode_settings.get("ymax", "")),
                    key=f"ymax_{selected_stat}_{indiv_agg}",
                )
            with col_step:
                ystep = st.text_input(
                    "Lépés",
                    value=str(mode_settings.get("ystep", "")),
                    key=f"ystep_{selected_stat}_{indiv_agg}",
                )

            st.sidebar.markdown("---")
            st.sidebar.subheader("🔄 Akkumulált összeg zárójelben")
            show_acc_in_brackets = st.sidebar.checkbox(
                "Akkumulált összeg megjelenítése a pontok alatt",
                value=stat_settings.get("show_acc_in_brackets", False),
                key=f"show_acc_{selected_stat}",
            )
            initial_accumulated_val = st.sidebar.number_input(
                "Kezdő alap:",
                value=float(stat_settings.get("initial_accumulated_val", 0.0)),
                step=1.0,
                key=f"init_acc_{selected_stat}",
            )

            st.sidebar.markdown("---")
            st.sidebar.subheader(f"🛡️ Életvonal ({indiv_agg})")
            survival_value = st.sidebar.number_input(
                "Életvonal értéke:",
                value=float(mode_settings.get("survival_value", 0.0)),
                step=1.0,
                key=f"surv_val_{selected_stat}_{indiv_agg}",
            )
            show_survival_line = st.sidebar.checkbox(
                "Életvonal rajzolása a grafikonra",
                value=mode_settings.get("show_survival", True),
                key=f"show_surv_{selected_stat}_{indiv_agg}",
            )

            st.sidebar.markdown("---")
            st.sidebar.subheader(f"🎯 Célkitűzés ({indiv_agg})")
            goal_type_val = mode_settings.get("goal_type", "Nincs")
            goal_type = st.sidebar.selectbox(
                "Cél típusa:",
                valid_goals,
                index=valid_goals.index(goal_type_val)
                if goal_type_val in valid_goals
                else 0,
                key=f"goal_type_{selected_stat}_{indiv_agg}",
            )
            goal_value = st.sidebar.number_input(
                "Cél mértéke:",
                value=float(mode_settings.get("goal_val_target", 0.0)),
                step=1.0,
                key=f"goal_val_{selected_stat}_{indiv_agg}",
            )

            if "settings" not in st.session_state.db:
                st.session_state.db["settings"] = {}
            if selected_stat not in st.session_state.db["settings"]:
                st.session_state.db["settings"][selected_stat] = {}

            st.session_state.db["settings"][selected_stat][
                "person_name"
            ] = person_name
            st.session_state.db["settings"][selected_stat][
                "person_post"
            ] = person_post
            st.session_state.db["settings"][selected_stat][
                "chart_height"
            ] = chart_height
            st.session_state.db["settings"][selected_stat]["margin_l"] = margin_l
            st.session_state.db["settings"][selected_stat]["margin_r"] = margin_r
            st.session_state.db["settings"][selected_stat]["margin_t"] = margin_t
            st.session_state.db["settings"][selected_stat]["margin_b"] = margin_b
            st.session_state.db["settings"][selected_stat][
                "show_acc_in_brackets"
            ] = show_acc_in_brackets
            st.session_state.db["settings"][selected_stat][
                "initial_accumulated_val"
            ] = initial_accumulated_val

            st.session_state.db["settings"][selected_stat][indiv_agg] = {
                "chart_type": chart_type,
                "ymin": ymin,
                "ymax": ymax,
                "ystep": ystep,
                "survival_value": survival_value,
                "show_survival": show_survival_line,
                "goal_type": goal_type,
                "goal_val_target": goal_value,
            }

            st.session_state.db["stats"][selected_stat][
                "inverted"
            ] = is_stat_inverted_check

            current_settings_complete = st.session_state.db["settings"][selected_stat]
            settings_changed = (
                current_settings_complete != original_stat_settings
                or is_stat_inverted_check != original_inverted
            )

            if apply_all_requested:
                for s_loop in all_stat_names:
                    st.session_state.db["settings"][s_loop] = copy.deepcopy(
                        current_settings_complete
                    )
                    st.session_state.db["stats"][s_loop]["inverted"] = is_stat_inverted_check
                save_data(st.session_state.db)
                append_audit_event(
                    "Beállítások módosítása",
                    stat_name=selected_stat,
                    summary="Az aktuális grafikonbeállítások minden statisztikára átmásolva",
                    details={"applied_to": list(all_stat_names)},
                )
                st.sidebar.success("Minden statisztika megkapta az aktuális beállításokat!")
                st.rerun()
            elif settings_changed:
                save_data(st.session_state.db)
                append_audit_event(
                    "Beállítások módosítása",
                    stat_name=selected_stat,
                    summary="Statisztika grafikon/beállítás módosítva",
                    details={
                        "before": original_stat_settings,
                        "after": current_settings_complete,
                        "inverted_before": original_inverted,
                        "inverted_after": is_stat_inverted_check,
                    },
                )
        else:
            chart_type = mode_settings.get("chart_type", "Vonaldiagram")
            ymin = str(mode_settings.get("ymin", ""))
            ymax = str(mode_settings.get("ymax", ""))
            ystep = str(mode_settings.get("ystep", ""))
            show_acc_in_brackets = stat_settings.get("show_acc_in_brackets", False)
            initial_accumulated_val = float(
                stat_settings.get("initial_accumulated_val", 0.0)
            )
            survival_value = float(mode_settings.get("survival_value", 0.0))
            show_survival_line = mode_settings.get("show_survival", True)
            goal_type = mode_settings.get("goal_type", "Nincs")
            goal_value = float(mode_settings.get("goal_val_target", 0.0))

        components.html(
            """
            <button onclick="window.parent.print()" style="
                padding: 10px 20px; 
                font-size: 15px; 
                background-color: #000000; 
                color: white; 
                border: none; 
                border-radius: 8px; 
                cursor: pointer;
                font-weight: bold;
                box-shadow: 0px 4px 6px rgba(0,0,0,0.1);
            ">🖨️ Nyomtatás A4-re</button>
        """,
            height=50,
        )

        if stat_desc:
            st.info(f"ℹ️ **Útmutató a statisztikához:** {stat_desc}")

        stat_data_raw = db["stats"][selected_stat]["data"]

        if stat_data_raw:
            df_temp = pd.DataFrame(
                [
                    [item[0], item[1], item[2] if len(item) > 2 else ""]
                    for item in stat_data_raw
                    if isinstance(item, (list, tuple)) and len(item) >= 2
                ],
                columns=["Dátum", "Érték", "Megjegyzés"],
            )
            df_temp["Sort_Key"] = pd.to_datetime(
                df_temp["Dátum"], format="mixed", errors="coerce"
            )
            df_temp["Érték"] = pd.to_numeric(df_temp["Érték"], errors="coerce")
            invalid_chart_rows = int(df_temp[["Sort_Key", "Érték"]].isna().any(axis=1).sum())
            if invalid_chart_rows:
                st.warning(
                    f"⚠️ {invalid_chart_rows} hibás dátumú vagy nem numerikus sor kimaradt a grafikonból. "
                    "Az Adat-táblázatban javítható."
                )
            df_temp = df_temp.dropna(subset=["Sort_Key", "Érték"]).sort_values("Sort_Key")

            if indiv_agg == WEEKLY_LABEL:
                df_temp["Period_End"] = df_temp["Sort_Key"].apply(
                    get_thursday_period_end
                )
                res_df = (
                    df_temp.groupby("Period_End")
                    .agg({
                        "Érték": "sum",
                        "Megjegyzés": lambda x: " | ".join(
                            [str(n) for n in x if n and str(n).strip()]
                        ),
                    })
                    .reset_index()
                    .sort_values("Period_End")
                )

                raw_items = []
                for idx, row in res_df.iterrows():
                    d_str = row["Period_End"].strftime("%Y-%m-%d")
                    raw_items.append({
                        "x": len(raw_items),
                        "date_str": d_str,
                        "label": row["Period_End"].strftime("%Y. %m. %d."),
                        "hover_label": row["Period_End"].strftime("%Y. %m. %d."),
                        "val": float(row["Érték"]),
                        "note": row["Megjegyzés"],
                    })
                unique_x = list(range(len(raw_items)))
                unique_labels = [item["label"] for item in raw_items]

            elif indiv_agg == MONTHLY_LABEL:
                df_temp["Period_Month"] = (
                    df_temp["Sort_Key"]
                    .dt.to_period("M")
                    .dt.to_timestamp(how="end")
                    .dt.floor("D")
                )
                res_df = (
                    df_temp.groupby("Period_Month")
                    .agg({
                        "Sort_Key": "min",
                        "Érték": "sum",
                        "Megjegyzés": lambda x: " | ".join(
                            [str(n) for n in x if n and str(n).strip()]
                        ),
                    })
                    .reset_index()
                    .sort_values("Period_Month")
                )

                raw_items = []
                for idx, row in res_df.iterrows():
                    m_dt = row["Period_Month"]
                    d_str = m_dt.strftime("%Y-%m-%d")
                    raw_items.append({
                        "x": len(raw_items),
                        "date_str": d_str,
                        "label": m_dt.strftime("%Y. %m."),
                        "hover_label": m_dt.strftime("%Y. %m. hó"),
                        "val": float(row["Érték"]),
                        "note": row["Megjegyzés"],
                    })
                unique_x = list(range(len(raw_items)))
                unique_labels = [item["label"] for item in raw_items]

            else:
                # A napi nézet naptári nap szerint aggregál. A csütörtök 14:00-s
                # határ kizárólag a heti periódushoz tartozik, így nincs két,
                # egymásra rajzolt pont ugyanazon a napon.
                df_temp["Date_Only"] = df_temp["Sort_Key"].dt.strftime("%Y-%m-%d")
                res_df = (
                    df_temp.groupby("Date_Only", sort=False)
                    .agg({
                        "Sort_Key": "min",
                        "Érték": "sum",
                        "Megjegyzés": lambda x: " | ".join(
                            [str(n) for n in x if n and str(n).strip()]
                        ),
                    })
                    .reset_index()
                    .sort_values("Sort_Key")
                )

                raw_items = []
                for _, row in res_df.iterrows():
                    d_only = row["Date_Only"]
                    d_obj = datetime.strptime(d_only, "%Y-%m-%d")
                    fmt_d = f"{d_obj.year}. {d_obj.month:02d}. {d_obj.day:02d}."
                    raw_items.append({
                        "x": len(raw_items),
                        "date_str": d_only,
                        "label": fmt_d,
                        "hover_label": fmt_d,
                        "val": float(row["Érték"]),
                        "note": row["Megjegyzés"],
                    })

                unique_x = list(range(len(raw_items)))
                unique_labels = [item["label"] for item in raw_items]

        else:
            raw_items = []
            unique_x = []
            unique_labels = []

        accumulated_vals = []
        if raw_items:
            running_tot = float(initial_accumulated_val)
            for item in raw_items:
                running_tot += item["val"]
                accumulated_vals.append(running_tot)

        calc_survival_val = (
            survival_value if (show_survival_line and survival_value > 0) else 0.0
        )

        calc_goal_val = 0.0
        if goal_type == "Fix érték (db/Ft)":
            calc_goal_val = goal_value

        if stat_data_raw:
            date_range_str = ""
            if len(raw_items) > 0:
                try:
                    start_d = datetime.strptime(
                        raw_items[0]["date_str"], "%Y-%m-%d"
                    ).strftime("%Y. %m. %d.")
                    end_d = datetime.strptime(
                        raw_items[-1]["date_str"], "%Y-%m-%d"
                    ).strftime("%Y. %m. %d.")
                    date_range_str = f"({start_d} - {end_d})"
                except Exception:
                    date_range_str = ""

            fig = go.Figure()

            if len(raw_items) > 0:
                x_numeric = [item["x"] for item in raw_items]
                y_vals = [item["val"] for item in raw_items]
                notes = [item["note"] for item in raw_items]

                formatted_texts = []
                for idx, val in enumerate(y_vals):
                    v_str = fmt_num(val, current_unit)
                    if show_acc_in_brackets and accumulated_vals:
                        acc_val = accumulated_vals[idx]
                        acc_str = fmt_num(acc_val, current_unit)
                        formatted_texts.append(
                            f"{v_str}<br><span style='font-size:13px;"
                            f" color:#475569;'>({acc_str})</span>"
                        )
                    else:
                        formatted_texts.append(v_str)

                hover_texts = []
                for item, val, acc in zip(raw_items, y_vals, accumulated_vals):
                    v_str = fmt_num(val, current_unit)
                    acc_str = fmt_num(acc, current_unit)
                    h_txt = (
                        f"Dátum: {item['hover_label']}<br>Érték: {v_str}<br>Akkumulált:"
                        f" {acc_str}"
                    )
                    if item["note"]:
                        h_txt += f"<br>Megjegyzés: {item['note']}"
                    hover_texts.append(h_txt)

                if chart_type == "Oszlopdiagram (Bar)":
                    bar_colors = []
                    for i, y_val in enumerate(y_vals):
                        if i == 0:
                            bar_colors.append("#00C853")
                        else:
                            prev_y = y_vals[i - 1]
                            if is_stat_inverted_check:
                                c = "#00C853" if y_val < prev_y else "#FF1744"
                            else:
                                c = "#00C853" if y_val > prev_y else "#FF1744"
                            bar_colors.append(c)

                    fig.add_trace(
                        go.Bar(
                            x=x_numeric,
                            y=y_vals,
                            marker=dict(color=bar_colors),
                            hovertext=hover_texts,
                            hoverinfo="text",
                            showlegend=False,
                        )
                    )
                else:
                    for i in range(len(raw_items) - 1):
                        x1, y1 = x_numeric[i], y_vals[i]
                        x2, y2 = x_numeric[i + 1], y_vals[i + 1]

                        if is_stat_inverted_check:
                            color = "#00C853" if y2 < y1 else "#FF1744"
                        else:
                            color = "#00C853" if y2 > y1 else "#FF1744"

                        fig.add_trace(
                            go.Scatter(
                                x=[x1, x2],
                                y=[y1, y2],
                                mode="lines",
                                line=dict(color=color, width=6),
                                showlegend=False,
                                hoverinfo="skip",
                            )
                        )

                    fig.add_trace(
                        go.Scatter(
                            x=x_numeric,
                            y=y_vals,
                            mode="markers",
                            marker=dict(size=16, color="#1E293B"),
                            cliponaxis=False,
                            hovertext=hover_texts,
                            hoverinfo="text",
                            showlegend=False,
                        )
                    )

                if show_survival_line and calc_survival_val > 0:
                    fig.add_hline(
                        y=calc_survival_val,
                        line_dash="solid",
                        line_color="#4B5563",
                        line_width=4,
                    )

                for idx, (x_val, y_val, txt) in enumerate(
                    zip(x_numeric, y_vals, formatted_texts)
                ):
                    fig.add_annotation(
                        x=x_val,
                        y=y_val,
                        text=txt,
                        showarrow=False,
                        yshift=12,
                        xshift=18,
                        textangle=-75,
                        font=dict(size=14, color="#000000", family="Arial Black"),
                        xanchor="center",
                        yanchor="bottom",
                    )

                if person_name:
                    fig.add_annotation(
                        xref="paper",
                        yref="paper",
                        x=0.0,
                        y=1.15,
                        text=f"<b>{person_name}</b>",
                        showarrow=False,
                        align="left",
                        xanchor="left",
                        yanchor="bottom",
                        font=dict(size=26, family="Arial Black", color="#000000"),
                    )
                if person_post:
                    fig.add_annotation(
                        xref="paper",
                        yref="paper",
                        x=0.0,
                        y=1.05,
                        text=person_post,
                        showarrow=False,
                        align="left",
                        xanchor="left",
                        yanchor="bottom",
                        font=dict(size=20, family="Arial Black", color="#000000"),
                    )

                if goal_type != "Nincs" and calc_goal_val > 0:
                    goal_fmt = fmt_num(calc_goal_val, current_unit)
                    fig.add_annotation(
                        xref="paper",
                        yref="paper",
                        x=1.0,
                        y=1.08,
                        text=f"Cél: {goal_fmt}",
                        showarrow=False,
                        align="right",
                        xanchor="right",
                        yanchor="bottom",
                        font=dict(size=20, color="#C5A059", family="Arial Black"),
                    )

                # --- TENGELY SKÁLA ÉS ROBUSTUS FORDÍTOTT TARTOMÁNY KEZELÉS ---
                yaxis_dict = dict(
                    title=dict(text="", font=dict(color="#000000", size=1)),
                    showgrid=True,
                    gridcolor="#F1F5F9",
                    gridwidth=3,
                    tickfont=dict(color="#000000", size=20, family="Arial Black"),
                    showline=True,
                    linecolor="#000000",
                    linewidth=3.5,
                    mirror=True,
                )

                has_custom_range = False
                try:
                    if (
                        ymin is not None
                        and str(ymin).strip() != ""
                        and ymax is not None
                        and str(ymax).strip() != ""
                    ):
                        clean_ymin = str(ymin).replace(",", ".").replace(" ", "").strip()
                        clean_ymax = str(ymax).replace(",", ".").replace(" ", "").strip()
                        f_min = float(clean_ymin)
                        f_max = float(clean_ymax)

                        if is_stat_inverted_check:
                            yaxis_dict["range"] = [f_max, f_min]
                        else:
                            yaxis_dict["range"] = [f_min, f_max]
                        has_custom_range = True
                except Exception:
                    pass

                if not has_custom_range:
                    if is_stat_inverted_check:
                        yaxis_dict["autorange"] = "reversed"
                    else:
                        yaxis_dict["rangemode"] = "tozero"

                if ystep is not None and str(ystep).strip() != "":
                    try:
                        clean_ystep = str(ystep).replace(",", ".").replace(" ", "").strip()
                        yaxis_dict["dtick"] = float(clean_ystep)
                    except Exception:
                        pass

                xaxis_range = [0, max(unique_x) + 0.5] if len(unique_x) > 1 else [0, 0.5]

                layout_args = dict(
                    title=dict(
                        text=(
                            f"<b>{selected_stat}</b><br><span style='font-size: 20px;"
                            f" color: #1E293B;'>Időszak: {date_range_str}"
                            f" ({indiv_agg})</span>"
                        ),
                        x=0.5,
                        xref="paper",
                        xanchor="center",
                        yanchor="top",
                        font=dict(size=30, color="#000000"),
                    ),
                    plot_bgcolor="white",
                    paper_bgcolor="white",
                    autosize=True,
                    height=chart_height,
                    margin=dict(t=margin_t, b=margin_b, l=margin_l, r=margin_r),
                    xaxis=dict(
                        title=dict(text="", font=dict(color="#000000", size=1)),
                        tickmode="array",
                        tickvals=unique_x,
                        ticktext=unique_labels,
                        tickangle=-30,
                        showgrid=True,
                        gridcolor="#F1F5F9",
                        gridwidth=3,
                        tickfont=dict(color="#000000", size=15, family="Arial Black"),
                        showline=True,
                        linecolor="#000000",
                        linewidth=3.5,
                        mirror=True,
                        range=xaxis_range,
                    ),
                    yaxis=yaxis_dict,
                )

                fig.update_layout(**layout_args)
                st.plotly_chart(fig, use_container_width=True)

        st.markdown("---")

        # --- ÚJ ADAT HOZZÁADÁSA ---
        st.subheader(f"➕ Új Adat Hozzáadása ({selected_stat})")

        with st.form("add_data_form", clear_on_submit=True):
            col_d, col_t = st.columns(2)
            with col_d:
                input_date = st.date_input("Dátum", value=budapest_now().date())
            with col_t:
                input_time = st.time_input("Időpont", value=budapest_now().time().replace(second=0, microsecond=0, tzinfo=None))

            input_val = st.number_input(
                f"Érték ({current_unit})", min_value=0.0, step=1.0
            )
            input_note = st.text_input("Megjegyzés / Esemény ehhez a ponthoz:")
            if st.form_submit_button("Adat Hozzáadása"):
                full_dt_str = (
                    f"{input_date.strftime('%Y-%m-%d')} {input_time.strftime('%H:%M')}"
                )
                st.session_state.db["stats"][selected_stat]["data"].append(
                    [full_dt_str, input_val, input_note]
                )
                st.session_state.db["stats"][selected_stat]["data"] = sorted(
                    st.session_state.db["stats"][selected_stat]["data"],
                    key=_stat_data_sort_key,
                )
                save_data(st.session_state.db)
                append_audit_event(
                    "Adat hozzáadása",
                    stat_name=selected_stat,
                    summary=f"Kézi adat rögzítve: {full_dt_str} | {input_val} {current_unit}",
                    details={
                        "row": [full_dt_str, input_val, input_note],
                        "source": "kézi adatbevitel",
                    },
                )
                st.success("Adat hozzáadva!")
                st.rerun()

        st.markdown("---")

        # --- MINICRM / EXCEL IMPORT ---
        with st.expander("📥 MiniCRM / Excel import", expanded=False):
            st.caption(
                "A teljes MiniCRM Excel táblát használhatod. A SCART a bevételhez a dátumot és "
                "a **Számla: Nettó összeg** értékét használja. Elsődlegesen a kifizetés dátumát "
                "veszi; ha az üres, a kiállítás dátumára teszi az összeget."
            )
            st.info(
                "Csak a **Fizetve** státuszú E-számlák számítanak bele. Az E-díjbekérő, "
                "**Kiállítva**, **Sztornózva** és **Sztornó** sorokat kihagyja. A feldolgozás után "
                "a dátumokat és összegeket egy szerkeszthető táblázatban ellenőrizheted, és csak "
                "a véglegesítés után kerülnek be a statisztikába."
            )

            excel_default_time = st.time_input(
                "Importált dátumok időpontja:",
                value=datetime.strptime("14:00", "%H:%M").time(),
                key=f"excel_default_time_{selected_stat}",
            )

            import_mode = st.radio(
                "Hogyan szeretnéd betölteni?",
                ["MiniCRM Excel fájl (.xlsx)", "Beillesztés Excelből"],
                horizontal=True,
                key=f"excel_import_mode_{selected_stat}",
            )

            draft_key = f"_minicrm_import_draft_{selected_stat}"
            draft_seq_key = f"_minicrm_import_draft_seq_{selected_stat}"
            imported_rows = []
            import_errors = []
            import_stats = {}
            import_requested = False

            if import_mode == "MiniCRM Excel fájl (.xlsx)":
                minicrm_file = st.file_uploader(
                    "MiniCRM Excel kiválasztása",
                    type=["xlsx", "xlsm"],
                    key=f"minicrm_file_{selected_stat}",
                )
                if minicrm_file is not None:
                    imported_rows, import_errors, import_stats = parse_minicrm_excel_file(
                        minicrm_file, excel_default_time
                    )
                    if import_errors:
                        st.error(
                            "A MiniCRM fájl feldolgozásakor hiba történt:\n- "
                            + "\n- ".join(import_errors[:30])
                        )
                    else:
                        st.caption(
                            f"Feldolgozható napi sorok: **{len(imported_rows)}**. "
                            "A következő gombbal nyisd meg őket szerkesztésre."
                        )
                    import_requested = st.button(
                        "🧾 Feldolgozás és szerkesztés",
                        key=f"minicrm_prepare_btn_{selected_stat}",
                        disabled=bool(import_errors) or not bool(
                            imported_rows or import_stats.get("covered_dates")
                        ),
                    )
            else:
                st.caption(
                    "Nyisd meg a MiniCRM-ből exportált Excelt, jelöld ki a teljes táblázatot "
                    "a fejléccel együtt, másold ki, majd illeszd be ide."
                )
                with st.form(f"excel_paste_form_{selected_stat}", clear_on_submit=True):
                    excel_paste = st.text_area(
                        "Excelből bemásolt MiniCRM adatok:",
                        height=220,
                        placeholder=(
                            "Adatlap: Azonosító\t...\tSzámla: Kifizetés dátuma\tSzámla: Nettó összeg\n"
                            "...\t...\t2026-10-13\t97500"
                        ),
                        key=f"excel_paste_{selected_stat}",
                    )
                    import_requested = st.form_submit_button(
                        "🧾 Feldolgozás és szerkesztés"
                    )
                if import_requested:
                    imported_rows, import_errors, import_stats = parse_excel_paste(
                        excel_paste, excel_default_time
                    )

            if import_requested:
                if import_errors:
                    st.error(
                        "A SCART nem mentett semmit, mert hibás sorokat talált:\n- "
                        + "\n- ".join(import_errors[:30])
                    )
                    if len(import_errors) > 30:
                        st.warning(f"További {len(import_errors) - 30} hibás sor is található.")
                elif not imported_rows and not import_stats.get("covered_dates"):
                    st.warning("Nem találtam importálható vagy újraszámolható MiniCRM dátumot.")
                else:
                    next_seq = int(st.session_state.get(draft_seq_key, 0)) + 1
                    st.session_state[draft_seq_key] = next_seq
                    st.session_state[draft_key] = {
                        "rows": copy.deepcopy(imported_rows),
                        "stats": copy.deepcopy(import_stats),
                        "seq": next_seq,
                    }

            draft = st.session_state.get(draft_key)
            if draft is not None:
                st.markdown("### ✏️ Import ellenőrzése és javítása")
                st.caption(
                    "A MiniCRM-ből feldolgozott adatok még **nincsenek elmentve**. "
                    "Itt ugyanúgy átírhatod a dátumot, időpontot és összeget, új sort is "
                    "hozzáadhatsz, illetve sort törölhetsz. A véglegesítés után ezek az adatok "
                    "a lentebbi normál SCART adat-táblázatban is szerkeszthetők maradnak."
                )

                draft_rows = draft.get("rows", [])
                preview_rows = []
                for item in draft_rows:
                    dt_str = str(item[0]).strip() if len(item) > 0 else ""
                    parts = dt_str.split()
                    d_part = parts[0] if parts else ""
                    t_part = parts[1] if len(parts) > 1 else "14:00"
                    v_part = item[1] if len(item) > 1 else 0
                    n_part = item[2] if len(item) > 2 else ""
                    preview_rows.append([d_part, t_part, v_part, n_part])

                import_value_col = f"Érték ({current_unit})"
                import_preview_df = pd.DataFrame(
                    preview_rows,
                    columns=["Dátum", "Időpont", import_value_col, "Megjegyzés"],
                )

                with st.form(f"minicrm_edit_import_form_{selected_stat}_{draft.get('seq', 0)}"):
                    edited_import_df = st.data_editor(
                        import_preview_df,
                        num_rows="dynamic",
                        use_container_width=True,
                        hide_index=True,
                        column_config={
                            "Dátum": st.column_config.TextColumn(
                                "Dátum (ÉÉÉÉ-HH-NN)", help="pl. 2026-10-06"
                            ),
                            "Időpont": st.column_config.TextColumn(
                                "Időpont (ÓÓ:PP)", help="pl. 14:00"
                            ),
                            import_value_col: st.column_config.NumberColumn(
                                import_value_col, step=1.0
                            ),
                            "Megjegyzés": st.column_config.TextColumn(
                                "Megjegyzés", help="Ide kézzel is írhatsz korrekciós megjegyzést."
                            ),
                        },
                        key=f"minicrm_import_editor_{selected_stat}_{draft.get('seq', 0)}",
                    )
                    col_import_save, col_import_cancel = st.columns(2)
                    with col_import_save:
                        finalize_import = st.form_submit_button(
                            "💾 Javított adatok végleges importálása",
                            type="primary",
                            use_container_width=True,
                        )
                    with col_import_cancel:
                        cancel_import = st.form_submit_button(
                            "❌ Import előnézet elvetése",
                            use_container_width=True,
                        )

                if cancel_import:
                    st.session_state.pop(draft_key, None)
                    st.rerun()

                if finalize_import:
                    finalized_rows = []
                    validation_errors = []
                    for row_index, row in edited_import_df.iterrows():
                        d_val = str(row["Dátum"]).strip() if pd.notnull(row["Dátum"]) else ""
                        t_val = str(row["Időpont"]).strip() if pd.notnull(row["Időpont"]) else "14:00"
                        if not t_val or t_val == "nan":
                            t_val = "14:00"

                        # Üres dátum = a felhasználó törölte a sort az importból.
                        if not d_val or d_val == "nan":
                            continue

                        parsed_dt, numeric_val, row_errors = validate_table_row(
                            d_val, t_val, row[import_value_col]
                        )
                        if row_errors:
                            validation_errors.append(
                                f"{int(row_index) + 1}. sor: {', '.join(row_errors)}"
                            )
                            continue

                        v_val = float(numeric_val)
                        if v_val.is_integer():
                            v_val = int(v_val)
                        n_val = (
                            str(row["Megjegyzés"]).strip()
                            if pd.notnull(row["Megjegyzés"]) and str(row["Megjegyzés"]) != "nan"
                            else ""
                        )
                        finalized_rows.append(
                            [parsed_dt.strftime("%Y-%m-%d %H:%M"), v_val, n_val]
                        )

                    if validation_errors:
                        st.error(
                            "Az import még nincs elmentve. Javítsd az alábbi sorokat:\n- "
                            + "\n- ".join(validation_errors[:30])
                        )
                    else:
                        finalized_rows.sort(key=_stat_data_sort_key)
                        draft_stats = draft.get("stats", {})
                        covered_dates = set(draft_stats.get("covered_dates", []))
                        edited_dates = {row[0][:10] for row in finalized_rows}
                        # MiniCRM teljes snapshotnál minden lefedett nap újraszámolódik,
                        # hogy a később Sztornózva státuszúvá vált régi számla is eltűnjön
                        # az eredeti időszakból. Kézi/simple importnál csak a ténylegesen
                        # szerkesztett dátumokat cseréljük.
                        replace_dates = (covered_dates | edited_dates) if covered_dates else edited_dates

                        old_rows = st.session_state.db["stats"][selected_stat]["data"]
                        kept_rows = []
                        replaced_rows = 0
                        for old_row in old_rows:
                            try:
                                row_day = pd.to_datetime(
                                    str(old_row[0]), format="mixed", errors="coerce"
                                )
                                row_day = (
                                    row_day.strftime("%Y-%m-%d")
                                    if pd.notna(row_day)
                                    else None
                                )
                            except Exception:
                                row_day = None
                            if row_day in replace_dates:
                                replaced_rows += 1
                            else:
                                kept_rows.append(old_row)

                        kept_rows.extend(finalized_rows)
                        st.session_state.db["stats"][selected_stat]["data"] = sorted(
                            kept_rows, key=_stat_data_sort_key
                        )
                        save_data(st.session_state.db)
                        append_audit_event(
                            "MiniCRM/Excel import",
                            stat_name=selected_stat,
                            summary=(
                                f"{len(finalized_rows)} dátumsor véglegesítve; "
                                f"{replaced_rows} korábbi sor újraszámolva"
                            ),
                            details={
                                "imported_rows": finalized_rows,
                                "replaced_rows_count": replaced_rows,
                                "covered_dates": sorted(replace_dates),
                                "import_stats": draft_stats,
                            },
                        )

                        skipped = (
                            int(draft_stats.get("skipped_no_date", 0))
                            + int(draft_stats.get("source_skipped_no_date", 0))
                            + int(draft_stats.get("skipped_bad_value", 0))
                            + int(draft_stats.get("skipped_negative", 0))
                        )
                        extra_parts = []
                        if replaced_rows:
                            extra_parts.append(f"{replaced_rows} korábbi sor újraszámolva")
                        fallback_count = int(draft_stats.get("fallback_issue_date", 0))
                        if fallback_count:
                            extra_parts.append(
                                f"{fallback_count} tétel kiállítás dátumával számolva"
                            )
                        proforma_count = int(draft_stats.get("skipped_proforma", 0))
                        if proforma_count:
                            extra_parts.append(f"{proforma_count} díjbekérő kihagyva")
                        issued_count = int(draft_stats.get("skipped_issued", 0))
                        if issued_count:
                            extra_parts.append(f"{issued_count} Kiállítva státusz kihagyva")
                        cancelled_count = int(
                            draft_stats.get("skipped_cancelled_original", 0)
                        )
                        cancel_note_count = int(draft_stats.get("skipped_cancel_note", 0))
                        if cancelled_count or cancel_note_count:
                            extra_parts.append(
                                f"{cancelled_count} Sztornózva + "
                                f"{cancel_note_count} Sztornó sor kihagyva"
                            )
                        other_status = int(draft_stats.get("skipped_other_status", 0))
                        if other_status:
                            extra_parts.append(f"{other_status} egyéb státusz kihagyva")
                        if skipped:
                            extra_parts.append(f"{skipped} nem használható sor kihagyva")

                        extra = "; " + "; ".join(extra_parts) if extra_parts else ""
                        st.session_state.pop(draft_key, None)
                        st.session_state["_scart_flash_success"] = (
                            f"✅ {len(finalized_rows)} javított napi sor importálva{extra}. "
                            "Az adatok lent, a normál SCART táblázatban tovább szerkeszthetők."
                        )
                        st.rerun()

        if "_scart_flash_success" in st.session_state:
            st.success(st.session_state.pop("_scart_flash_success"))

        st.markdown("---")

        # --- ADAT-TÁBLÁZAT, HÓNAP SZŰRÉS ÉS AUTOMATIKUS MENTÉS ---
        if table_month_key:
            st.subheader(
                f"📋 Adat-táblázat – {table_month_date.year}. {table_month_date.month:02d}. hónap"
            )
            st.caption(
                "Csak a kiválasztott hónap sorai láthatók. A többi hónap adatai a háttérben "
                "változatlanul megmaradnak. A cellák módosítása és az új sorok kitöltése "
                "automatikusan mentődik."
            )
        else:
            st.subheader("📋 Adat-táblázat – összes adat")
            st.caption(
                "Minden rögzített sor látható. A cellák módosítása és az új sorok kitöltése "
                "automatikusan mentődik."
            )

        full_stat_data = db["stats"][selected_stat].get("data", [])
        visible_source_rows = []
        hidden_malformed_rows = 0

        for item in full_stat_data:
            if not isinstance(item, (list, tuple)) or len(item) < 2:
                hidden_malformed_rows += 1
                continue

            if table_month_key is None:
                visible_source_rows.append(item)
                continue

            item_ts = pd.to_datetime(str(item[0]), format="mixed", errors="coerce")
            if pd.isna(item_ts):
                # Hibás régi sorhoz nem nyúlunk hónapszűrés közben; a háttérben megmarad.
                hidden_malformed_rows += 1
                continue
            if pd.Timestamp(item_ts).strftime("%Y-%m") == table_month_key:
                visible_source_rows.append(item)

        table_rows = []
        for item in visible_source_rows:
            dt_str = str(item[0]).strip()
            parts = dt_str.split()
            d_part = parts[0] if len(parts) > 0 else ""
            t_part = parts[1] if len(parts) > 1 else "00:00"

            try:
                v_part = float(item[1])
                if v_part.is_integer():
                    v_part = int(v_part)
            except (ValueError, TypeError):
                v_part = str(item[1])

            n_part = (
                str(item[2]).strip()
                if len(item) > 2 and item[2] is not None and str(item[2]) != "nan"
                else ""
            )
            table_rows.append([d_part, t_part, v_part, n_part])

        if hidden_malformed_rows:
            st.warning(
                f"⚠️ {hidden_malformed_rows} régi/szerkezetileg hibás sor nincs ebben a "
                "hónapnézetben, de a SCART megőrzi és nem törli."
            )

        value_col = f"Érték ({current_unit})"
        df_raw = pd.DataFrame(
            table_rows,
            columns=["Dátum", "Időpont", value_col, "Megjegyzés"],
        )

        editor_revision = int(db.get("_meta", {}).get("revision", 0))
        editor_month_token = table_month_key or "ALL"
        edited_df = st.data_editor(
            df_raw,
            num_rows="dynamic",
            use_container_width=True,
            hide_index=True,
            column_config={
                "Dátum": st.column_config.TextColumn(
                    "Dátum (ÉÉÉÉ-HH-NN)", help="pl. 2026-10-06"
                ),
                "Időpont": st.column_config.TextColumn(
                    "Időpont (ÓÓ:PP)", help="pl. 13:28"
                ),
                value_col: st.column_config.NumberColumn(value_col, step=1.0),
                "Megjegyzés": st.column_config.TextColumn("Megjegyzés"),
            },
            key=f"editor_auto_{selected_stat}_{editor_month_token}_{editor_revision}",
        )

        def _canonical_existing_rows(rows):
            canonical = []
            for source_row in rows:
                if not isinstance(source_row, (list, tuple)) or len(source_row) < 2:
                    continue
                parsed = pd.to_datetime(
                    str(source_row[0]), format="mixed", errors="coerce"
                )
                numeric = pd.to_numeric(source_row[1], errors="coerce")
                if pd.isna(parsed) or pd.isna(numeric):
                    canonical.append(
                        [
                            str(source_row[0]).strip(),
                            str(source_row[1]).strip(),
                            str(source_row[2]).strip() if len(source_row) > 2 else "",
                        ]
                    )
                    continue
                val = float(numeric)
                if val.is_integer():
                    val = int(val)
                note = (
                    str(source_row[2]).strip()
                    if len(source_row) > 2
                    and source_row[2] is not None
                    and str(source_row[2]) != "nan"
                    else ""
                )
                canonical.append(
                    [pd.Timestamp(parsed).strftime("%Y-%m-%d %H:%M"), val, note]
                )
            return canonical

        edited_rows = []
        validation_errors = []
        incomplete_rows = []
        for row_index, row in edited_df.iterrows():
            d_val = str(row["Dátum"]).strip() if pd.notnull(row["Dátum"]) else ""
            t_val = (
                str(row["Időpont"]).strip()
                if pd.notnull(row["Időpont"])
                else "00:00"
            )
            raw_value = row[value_col]
            n_val = (
                str(row["Megjegyzés"]).strip()
                if pd.notnull(row["Megjegyzés"]) and str(row["Megjegyzés"]) != "nan"
                else ""
            )

            value_is_blank = pd.isna(raw_value) or str(raw_value).strip() in {"", "nan"}
            if (not d_val or d_val == "nan") and value_is_blank and not n_val:
                continue

            # Félbehagyott új sor esetén nem mentünk még, hogy gépelés közben megmaradjon.
            if not d_val or d_val == "nan" or value_is_blank:
                incomplete_rows.append(int(row_index) + 1)
                continue

            if not t_val or t_val == "nan":
                t_val = "00:00"

            parsed_dt, numeric_val, row_errors = validate_table_row(
                d_val, t_val, raw_value
            )
            if row_errors:
                validation_errors.append(
                    f"{int(row_index) + 1}. sor: {', '.join(row_errors)}"
                )
                continue

            v_val = float(numeric_val)
            if v_val.is_integer():
                v_val = int(v_val)
            edited_rows.append(
                [parsed_dt.strftime("%Y-%m-%d %H:%M"), v_val, n_val]
            )

        current_normalized = sorted(
            _canonical_existing_rows(visible_source_rows), key=_stat_data_sort_key
        )
        edited_normalized = sorted(edited_rows, key=_stat_data_sort_key)
        table_changed = edited_normalized != current_normalized

        if validation_errors:
            st.error(
                "Az automatikus mentés várakozik, mert hibás sort találtam:\n- "
                + "\n- ".join(validation_errors[:20])
            )
        elif incomplete_rows:
            st.info(
                "✍️ A(z) "
                + ", ".join(str(i) for i in incomplete_rows[:10])
                + ". sor még nincs kész. Add meg legalább a dátumot és az értéket; "
                "utána a SCART automatikusan elmenti."
            )
        elif table_changed:
            # Hónapszűrésnél kizárólag a látható hónapot cseréljük.
            # Minden más hónap és minden rejtett legacy sor érintetlen marad.
            kept_rows = []
            for old_row in full_stat_data:
                if not isinstance(old_row, (list, tuple)) or len(old_row) < 2:
                    kept_rows.append(old_row)
                    continue

                if table_month_key is None:
                    continue

                old_ts = pd.to_datetime(
                    str(old_row[0]), format="mixed", errors="coerce"
                )
                if pd.isna(old_ts):
                    kept_rows.append(old_row)
                    continue
                if pd.Timestamp(old_ts).strftime("%Y-%m") != table_month_key:
                    kept_rows.append(old_row)

            kept_rows.extend(edited_rows)
            st.session_state.db["stats"][selected_stat]["data"] = sorted(
                kept_rows, key=_stat_data_sort_key
            )
            save_data(st.session_state.db)
            added_audit_rows, removed_audit_rows = _audit_row_diff(
                current_normalized, edited_normalized
            )
            append_audit_event(
                "Adattábla módosítása",
                stat_name=selected_stat,
                summary=_audit_summary_from_rows(
                    added_audit_rows, removed_audit_rows
                ),
                details={
                    "month_filter": table_month_key or "Összes adat",
                    "added_or_new_values": added_audit_rows,
                    "removed_or_previous_values": removed_audit_rows,
                },
            )
            st.session_state["_scart_table_autosave_flash"] = (
                "✅ Táblázat automatikusan elmentve. A többi hónap adatai nem változtak."
                if table_month_key
                else "✅ Táblázat automatikusan elmentve."
            )
            st.rerun()

        if "_scart_table_autosave_flash" in st.session_state:
            st.success(st.session_state.pop("_scart_table_autosave_flash"))

# 2. TÖBB STATISZTIKA ÖSSZEVETÉSE
elif selected_menu == "📈 Több Statisztika Összevetése":
    st.title(f"📈 {SCART_NAME} – Statisztikák Relatív Összevetése")
    if not stat_names:
        st.warning("⚠️ Nincs elérhető statisztika az összehasonlításhoz.")
    else:
        comp_period_type = st.radio(
            "Összehasonlítás alapja:",
            ["Napi", WEEKLY_LABEL, "Havi"],
            horizontal=True,
        )
        show_dates_on_chart = st.checkbox(
            "Eredeti dátumok megjelenítése a feliratokban", value=True
        )

        selected_multi_stats = st.multiselect(
            "Válassz statisztikákat az összevetéshez:",
            stat_names,
            default=stat_names[:2] if len(stat_names) >= 2 else stat_names,
            format_func=stat_label,
        )

        if selected_multi_stats:
            fig = go.Figure()
            color_palette = [
                "#1f77b4",
                "#ff7f0e",
                "#2ca02c",
                "#d62728",
                "#9467bd",
                "#8c564b",
                "#e377c2",
                "#7f7f7f",
                "#bcbd22",
                "#17becf",
            ]
            max_len = 0
            processed_series = []

            for stat_name in selected_multi_stats:
                stat_data = db["stats"][stat_name]["data"]
                s_unit = db["stats"][stat_name].get("unit", "")
                if not stat_data:
                    continue

                clean_data = [
                    [item[0], item[1]]
                    for item in stat_data
                    if isinstance(item, (list, tuple)) and len(item) >= 2
                ]
                df = pd.DataFrame(clean_data, columns=["Dátum", "Érték"])
                df["Sort_Key"] = pd.to_datetime(
                    df["Dátum"], format="mixed", errors="coerce"
                )
                df["Érték"] = pd.to_numeric(df["Érték"], errors="coerce")
                df = df.dropna(subset=["Sort_Key", "Érték"]).sort_values("Sort_Key")

                try:
                    if comp_period_type == "Napi":
                        df["Daily_Bucket"] = df["Sort_Key"].apply(
                            lambda dt: dt.strftime("%Y-%m-%d")
                        )
                        res = (
                            df.groupby(["Daily_Bucket"], sort=False)
                            .agg({"Sort_Key": "min", "Érték": "sum"})
                            .reset_index()
                            .sort_values("Sort_Key")
                            .rename(columns={"Daily_Bucket": "Dátum"})
                        )
                    elif comp_period_type == WEEKLY_LABEL:
                        df["Period_End"] = df["Sort_Key"].apply(get_thursday_period_end)
                        res = (
                            df.groupby("Period_End")
                            .agg({"Érték": "sum"})
                            .reset_index()
                            .rename(columns={"Period_End": "Dátum"})
                        )
                    else:
                        df["Period_Month"] = (
                            df["Sort_Key"]
                            .dt.to_period("M")
                            .dt.to_timestamp(how="end")
                            .dt.floor("D")
                        )
                        res = (
                            df.groupby("Period_Month")
                            .agg({"Érték": "sum"})
                            .reset_index()
                            .rename(columns={"Period_Month": "Dátum"})
                        )
                except Exception:
                    res = df

                res["Érték"] = res["Érték"].fillna(0)
                items = res[["Dátum", "Érték"]].values.tolist()
                if len(items) > max_len:
                    max_len = len(items)
                processed_series.append((stat_name, s_unit, items))

            if max_len > 0:
                for idx, (stat_name, s_unit, items) in enumerate(processed_series):
                    y_vals = [item[1] for item in items]
                    orig_dates = [
                        dt.strftime("%Y.%m.%d.")
                        if isinstance(dt, (pd.Timestamp, datetime))
                        else str(dt)
                        for dt, _ in items
                    ]

                    x_idx_current = list(range(1, len(y_vals) + 1))
                    formatted_texts = [fmt_num(y, s_unit) for y in y_vals]
                    trace_color = color_palette[idx % len(color_palette)]

                    fig.add_trace(
                        go.Scatter(
                            x=x_idx_current,
                            y=y_vals,
                            mode="lines+markers",
                            name=stat_name,
                            customdata=orig_dates,
                            hovertemplate=(
                                "<b>%{fullData.name}</b><br>Sorszám:"
                                " %{x}.<br><b>Dátum: %{customdata}</b><br>Érték:"
                                " %{text}<extra></extra>"
                            ),
                            text=formatted_texts,
                            line=dict(color=trace_color, width=5),
                            marker=dict(size=12, color=trace_color),
                            cliponaxis=False,
                        )
                    )

                    for x_val, y_val, txt, d_str in zip(
                        x_idx_current, y_vals, formatted_texts, orig_dates
                    ):
                        annotation_text = (
                            f"{txt}<br>({d_str})" if show_dates_on_chart else txt
                        )
                        fig.add_annotation(
                            x=x_val,
                            y=y_val,
                            text=annotation_text,
                            showarrow=False,
                            yshift=12,
                            xshift=18,
                            textangle=-75,
                            font=dict(size=11, color=trace_color, family="Arial Black"),
                            xanchor="center",
                            yanchor="bottom",
                        )

                fig.update_layout(
                    title=dict(
                        text=(
                            "<b>Statisztikák Relatív Összevetése"
                            f" ({comp_period_type})</b>"
                        ),
                        x=0.5,
                        font=dict(size=36, color="#000000"),
                    ),
                    plot_bgcolor="white",
                    paper_bgcolor="white",
                    height=650,
                    margin=dict(t=120, b=120, l=60, r=40),
                    xaxis=dict(
                        tickmode="array",
                        tickvals=list(range(1, max_len + 1)),
                        ticktext=[f"{i}." for i in range(1, max_len + 1)],
                        title=dict(
                            text="Relatív Időszak Sorszáma",
                            font=dict(size=16, color="#000000"),
                        ),
                        showgrid=True,
                        gridcolor="#F1F5F9",
                        gridwidth=2.5,
                        showline=True,
                        linecolor="#000000",
                        linewidth=3,
                        mirror=True,
                        tickfont=dict(color="#000000", size=15, family="Arial Black"),
                    ),
                    yaxis=dict(
                        rangemode="tozero",
                        showgrid=True,
                        gridcolor="#F1F5F9",
                        gridwidth=2.5,
                        showline=True,
                        linecolor="#000000",
                        linewidth=3,
                        mirror=True,
                        tickfont=dict(color="#000000", size=18, family="Arial Black"),
                    ),
                    legend=dict(
                        orientation="h",
                        yanchor="bottom",
                        y=1.02,
                        xanchor="right",
                        x=1,
                        font=dict(size=16),
                    ),
                )
                st.plotly_chart(fig, use_container_width=True)

# 3. ÖSSZESÍTŐ DASHBOARD (IDŐSZAKI BONTÁS KAPCSOLÓVAL)
elif selected_menu == "📋 Összesítő Dashboard (Kártya Nézet)":
    st.title(f"📋 {SCART_NAME} – Teljesítménymérő Dashboard")

    if not stat_names:
        st.warning("⚠️ Nincs számodra megjeleníthető statisztika.")
    else:
        col_dash_period, col_dash_group = st.columns([2, 2])
        with col_dash_period:
            dash_period = st.radio(
                "📅 Időszaki Bontás A Dashboardon:",
                [DAILY_LABEL, WEEKLY_LABEL, MONTHLY_LABEL, YEARLY_LABEL],
                horizontal=True,
                key="dash_period_select",
            )

        with col_dash_group:
            selected_group_filter = st.selectbox(
                "Szűrés csoport / részleg szerint:", ["Összes csoport"] + all_groups
            )

        col_search, _ = st.columns([4, 1])
        with col_search:
            search_query = st.text_input(
                "Keresés:",
                placeholder="Keresés a statisztikák között...",
                key="dash_search",
            )

        filtered_stats = []
        for s in stat_names:
            s_group = db["stats"][s].get("group", "Egyéb")
            if (
                selected_group_filter != "Összes csoport"
                and s_group != selected_group_filter
            ):
                continue
            if search_query and search_query.lower() not in s.lower():
                continue
            filtered_stats.append(s)

        if not filtered_stats:
            st.info("Nincs találat a megadott feltételeknek megfelelő statisztikára.")
        else:
            for i in range(0, len(filtered_stats), 2):
                cols = st.columns(2)
                for j in range(2):
                    if i + j < len(filtered_stats):
                        s_name = filtered_stats[i + j]
                        s_info = db["stats"][s_name]
                        s_data_raw = s_info["data"]
                        s_unit = s_info.get("unit", "")
                        s_group = s_info.get("group", "Egyéb")
                        s_settings = db.get("settings", {}).get(s_name, {})
                        s_inverted = s_info.get("inverted", False)

                        p_name = s_settings.get("person_name", "")
                        p_post = s_settings.get("person_post", "")
                        assigned_str = (
                            f"{p_name} ({p_post})" if p_name or p_post else "Nincs megadva"
                        )

                        if s_data_raw:
                            df_card = pd.DataFrame(
                                [
                                    [item[0], item[1], item[2] if len(item) > 2 else ""]
                                    for item in s_data_raw
                                    if isinstance(item, (list, tuple)) and len(item) >= 2
                                ],
                                columns=["Dátum", "Érték", "Megjegyzés"],
                            )
                            df_card["Sort_Key"] = pd.to_datetime(
                                df_card["Dátum"], format="mixed", errors="coerce"
                            )
                            df_card["Érték"] = pd.to_numeric(df_card["Érték"], errors="coerce")
                            df_card = df_card.dropna(subset=["Sort_Key", "Érték"]).sort_values("Sort_Key")

                            if dash_period == WEEKLY_LABEL:
                                df_card["Period_Key"] = df_card["Sort_Key"].apply(
                                    get_thursday_period_end
                                )
                                res_card = (
                                    df_card.groupby("Period_Key")
                                    .agg({
                                        "Érték": "sum",
                                        "Megjegyzés": lambda x: " | ".join(
                                            [str(n) for n in x if n and str(n).strip()]
                                        ),
                                    })
                                    .reset_index()
                                    .sort_values("Period_Key")
                                )

                                card_items = []
                                for _, row in res_card.iterrows():
                                    d_str = row["Period_Key"].strftime("%Y-%m-%d")
                                    card_items.append(
                                        [d_str, float(row["Érték"]), row["Megjegyzés"]]
                                    )

                            elif dash_period == MONTHLY_LABEL:
                                df_card["Period_Key"] = (
                                    df_card["Sort_Key"]
                                    .dt.to_period("M")
                                    .dt.to_timestamp(how="end")
                                    .dt.floor("D")
                                )
                                res_card = (
                                    df_card.groupby("Period_Key")
                                    .agg({
                                        "Érték": "sum",
                                        "Megjegyzés": lambda x: " | ".join(
                                            [str(n) for n in x if n and str(n).strip()]
                                        ),
                                    })
                                    .reset_index()
                                    .sort_values("Period_Key")
                                )

                                card_items = []
                                for _, row in res_card.iterrows():
                                    d_str = row["Period_Key"].strftime("%Y-%m-%d")
                                    card_items.append(
                                        [d_str, float(row["Érték"]), row["Megjegyzés"]]
                                    )

                            elif dash_period == YEARLY_LABEL:
                                df_card["Period_Key"] = (
                                    df_card["Sort_Key"]
                                    .dt.to_period("Y")
                                    .dt.to_timestamp(how="end")
                                    .dt.floor("D")
                                )
                                res_card = (
                                    df_card.groupby("Period_Key")
                                    .agg({
                                        "Érték": "sum",
                                        "Megjegyzés": lambda x: " | ".join(
                                            [str(n) for n in x if n and str(n).strip()]
                                        ),
                                    })
                                    .reset_index()
                                    .sort_values("Period_Key")
                                )

                                card_items = []
                                for _, row in res_card.iterrows():
                                    d_str = row["Period_Key"].strftime("%Y-%m-%d")
                                    card_items.append(
                                        [d_str, float(row["Érték"]), row["Megjegyzés"]]
                                    )

                            else:
                                card_items = sorted(s_data_raw, key=lambda x: str(x[0]))
                        else:
                            card_items = []

                        card_surv_val = 0.0
                        card_surv_threshold = 0.0
                        card_goal_type = "Nincs"
                        card_goal_target = 0.0
                        card_chart_type = "Vonaldiagram"

                        m_lookup_key = dash_period
                        if m_lookup_key in s_settings:
                            m_dict = s_settings[m_lookup_key]
                            card_chart_type = m_dict.get("chart_type", "Vonaldiagram")
                            card_surv_threshold = float(m_dict.get("survival_value", 0.0))
                            if m_dict.get("show_survival", True) and card_surv_threshold > 0:
                                card_surv_val = card_surv_threshold
                            if m_dict.get("goal_type", "Nincs") != "Nincs":
                                card_goal_type = m_dict.get("goal_type", "Nincs")
                                card_goal_target = float(m_dict.get("goal_val_target", 0.0))

                        card_y = (
                            [float(item[1]) for item in card_items] if card_items else []
                        )

                        card_calc_goal = 0.0
                        if card_goal_type == "Fix érték (db/Ft)":
                            card_calc_goal = card_goal_target

                        condition_text, condition_color = calculate_stat_condition(
                            card_items, card_surv_threshold, inverted=s_inverted
                        )

                        with cols[j]:
                            with st.container(border=True):
                                h_col1, h_col2 = st.columns([3, 1])
                                with h_col1:
                                    st.markdown(f"### **{s_name}**")
                                    st.caption(
                                        f"📁 **Részleg:** {s_group} | 👤 **Assigned to:**"
                                        f" {assigned_str}"
                                    )
                                with h_col2:
                                    color_map = {
                                        "green": "🟢",
                                        "blue": "🔵",
                                        "yellow": "🟡",
                                        "orange": "🟠",
                                        "red": "🔴",
                                        "gray": "⚪",
                                    }
                                    st.markdown(
                                        "<div style='text-align: right; font-weight: bold;"
                                        f" font-size: 14px;'>{color_map.get(condition_color, '⚪')}"
                                        f" {condition_text}</div>",
                                        unsafe_allow_html=True,
                                    )

                                if card_items:
                                    fig_card = go.Figure()
                                    x_num = list(range(len(card_items)))
                                    c_notes = [
                                        item[2] if len(item) > 2 else "" for item in card_items
                                    ]
                                    formatted_t = [fmt_num(y, s_unit) for y in card_y]

                                    x_fmt = []
                                    for item in card_items:
                                        dt_obj = pd.to_datetime(
                                            str(item[0]), format="mixed", errors="coerce"
                                        )
                                        if pd.notnull(dt_obj):
                                            if dash_period == YEARLY_LABEL:
                                                x_fmt.append(dt_obj.strftime("%Y"))
                                            elif dash_period == MONTHLY_LABEL:
                                                x_fmt.append(dt_obj.strftime("%Y.%m."))
                                            else:
                                                x_fmt.append(dt_obj.strftime("%b %d"))
                                        else:
                                            x_fmt.append(str(item[0]))

                                    hover_c = [
                                        (
                                            f"Dátum: {dt}<br>Érték: {txt}<br>Megjegyzés: {n}"
                                            if n
                                            else f"Dátum: {dt}<br>Érték: {txt}"
                                        )
                                        for dt, txt, n in zip(x_fmt, formatted_t, c_notes)
                                    ]

                                    if card_chart_type == "Oszlopdiagram (Bar)":
                                        c_bar_colors = []
                                        for k, y_val in enumerate(card_y):
                                            if k == 0:
                                                c_bar_colors.append("#00C853")
                                            else:
                                                prev_y = card_y[k - 1]
                                                if s_inverted:
                                                    c = "#00C853" if y_val < prev_y else "#FF1744"
                                                else:
                                                    c = "#00C853" if y_val > prev_y else "#FF1744"
                                                c_bar_colors.append(c)

                                        fig_card.add_trace(
                                            go.Bar(
                                                x=x_num,
                                                y=card_y,
                                                marker=dict(color=c_bar_colors),
                                                hovertext=hover_c,
                                                hoverinfo="text",
                                                showlegend=False,
                                            )
                                        )
                                    else:
                                        for k in range(len(card_items) - 1):
                                            x1, y1 = x_num[k], card_y[k]
                                            x2, y2 = x_num[k + 1], card_y[k + 1]
                                            color = (
                                                "#00C853"
                                                if (y2 < y1 if s_inverted else y2 > y1)
                                                else "#FF1744"
                                            )
                                            fig_card.add_trace(
                                                go.Scatter(
                                                    x=[x1, x2],
                                                    y=[y1, y2],
                                                    mode="lines",
                                                    line=dict(color=color, width=3.5),
                                                    showlegend=False,
                                                    hoverinfo="skip",
                                                )
                                            )

                                        fig_card.add_trace(
                                            go.Scatter(
                                                x=x_num,
                                                y=card_y,
                                                mode="markers",
                                                marker=dict(size=8, color="#1E293B"),
                                                cliponaxis=False,
                                                hovertext=hover_c,
                                                hoverinfo="text",
                                                showlegend=False,
                                            )
                                        )

                                    if card_surv_val > 0:
                                        fig_card.add_hline(
                                            y=card_surv_val,
                                            line_dash="solid",
                                            line_color="#4B5563",
                                            line_width=2.5,
                                        )

                                    if card_goal_type != "Nincs" and card_calc_goal > 0:
                                        fig_card.add_hline(
                                            y=card_calc_goal,
                                            line_dash="dash",
                                            line_color="#C5A059",
                                            line_width=2,
                                        )

                                    for x_val, y_val, txt in zip(x_num, card_y, formatted_t):
                                        fig_card.add_annotation(
                                            x=x_val,
                                            y=y_val,
                                            text=txt,
                                            showarrow=False,
                                            yshift=8,
                                            xshift=5,
                                            textangle=-75,
                                            font=dict(
                                                size=9, color="#000000", family="Arial Black"
                                            ),
                                            xanchor="center",
                                            yanchor="bottom",
                                        )

                                    yaxis_card = dict(
                                        showgrid=True,
                                        gridcolor="#F1F5F9",
                                        gridwidth=1.5,
                                        tickfont=dict(
                                            color="#000", size=11, family="Arial Black"
                                        ),
                                        showline=True,
                                        linecolor="#000",
                                        linewidth=1.5,
                                        mirror=True,
                                    )
                                    if s_inverted:
                                        yaxis_card["autorange"] = "reversed"
                                    else:
                                        yaxis_card["rangemode"] = "tozero"

                                    xaxis_card_range = [0, max(x_num) + 0.5] if len(x_num) > 1 else [0, 0.5]

                                    fig_card.update_layout(
                                        height=300,
                                        plot_bgcolor="white",
                                        paper_bgcolor="white",
                                        margin=dict(t=10, b=40, l=40, r=20),
                                        xaxis=dict(
                                            tickmode="array",
                                            tickvals=x_num,
                                            ticktext=x_fmt,
                                            tickangle=-30,
                                            showgrid=True,
                                            gridcolor="#F1F5F9",
                                            gridwidth=1.5,
                                            tickfont=dict(
                                                color="#000", size=10, family="Arial Black"
                                            ),
                                            showline=True,
                                            linecolor="#000",
                                            linewidth=1.5,
                                            mirror=True,
                                            range=xaxis_card_range,
                                        ),
                                        yaxis=yaxis_card,
                                    )
                                    st.plotly_chart(
                                        fig_card,
                                        use_container_width=True,
                                        config={"displayModeBar": False},
                                    )
                                else:
                                    st.info("Nincs megjeleníthető adat.")

# 4. ÚJ STATISZTIKA LÉTREHOZÁSA (CSAK ADMIN)
elif selected_menu == "➕ Új Statisztika Létrehozása":
    st.title(f"➕ {SCART_NAME} – Új Statisztika Létrehozása")
    with st.form("create_stat_form"):
        new_stat_name = st.text_input(
            "Statisztika neve:", placeholder="pl. Új Eladások"
        )
        new_stat_unit = st.text_input("Mértékegység:", placeholder="pl. Ft, db, fő")
        new_stat_group = st.selectbox("Csoport / Részleg:", options=all_groups)
        new_stat_desc = st.text_area(
            "Leírás / Útmutató (mit kell ide rögzíteni):",
            placeholder=(
                "Írd le pontosan, hogy mikor, mit és hogyan kell felvinni ebben a"
                " statisztikában..."
            ),
        )
        is_new_inverted = st.checkbox(
            "Fordított statisztika (a 0 felül van és lefelé nő)"
        )

        submit = st.form_submit_button("Létrehozás")
        if submit:
            if new_stat_name:
                if new_stat_name not in st.session_state.db["stats"]:
                    st.session_state.db["stats"][new_stat_name] = {
                        "unit": new_stat_unit,
                        "group": new_stat_group,
                        "inverted": is_new_inverted,
                        "description": new_stat_desc,
                        "data": [],
                    }
                    save_data(st.session_state.db)
                    append_audit_event(
                        "Statisztika létrehozása",
                        stat_name=new_stat_name,
                        summary=f"Új statisztika létrehozva: {new_stat_name}",
                        details={
                            "unit": new_stat_unit,
                            "group": new_stat_group,
                            "inverted": is_new_inverted,
                            "description": new_stat_desc,
                        },
                    )
                    st.success(f"Sikeresen létrehozva: {new_stat_name}")
                    st.rerun()
                else:
                    st.error("Ilyen nevű statisztika már létezik!")
            else:
                st.warning("Adj meg egy nevet!")

# 5. TEVÉKENYSÉGI NAPLÓ / "KÖNYV" (CSAK ADMIN)
elif selected_menu == "📖 Tevékenységi napló":
    st.title(f"📖 {SCART_NAME} – Admin tevékenységi napló")
    st.info(
        "Ez a napló nem szerkeszthető a felületről. Megmutatja, hogy ki, mikor és milyen "
        "fontos módosítást végzett. A v1.0.6 előtti műveletek felhasználója utólag nem "
        "állapítható meg; a napló a frissítés után kezd részletesen gyűjteni."
    )

    audit_entries = load_audit()
    if not audit_entries:
        st.info("A tevékenységi napló még üres. Az első új művelettől automatikusan telni fog.")
    else:
        audit_df = pd.DataFrame(audit_entries)
        for required_col in ["timestamp", "user", "role", "action", "stat", "summary", "id"]:
            if required_col not in audit_df.columns:
                audit_df[required_col] = ""
        audit_df["_ts"] = pd.to_datetime(audit_df["timestamp"], errors="coerce")
        audit_df = audit_df.sort_values("_ts", ascending=False, na_position="last")

        valid_ts = audit_df["_ts"].dropna()
        today = budapest_now().date()
        today_count = int((valid_ts.dt.date == today).sum()) if not valid_ts.empty else 0
        unique_users = int(audit_df["user"].replace("", pd.NA).dropna().nunique())
        last_event = (
            valid_ts.max().strftime("%Y.%m.%d. %H:%M:%S")
            if not valid_ts.empty
            else "–"
        )
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Összes naplóbejegyzés", len(audit_df))
        m2.metric("Mai események", today_count)
        m3.metric("Érintett felhasználók", unique_users)
        m4.metric("Utolsó esemény", last_event)

        st.markdown("### 🔎 Szűrés")
        f1, f2, f3 = st.columns(3)
        with f1:
            user_options = sorted(x for x in audit_df["user"].dropna().astype(str).unique() if x)
            selected_audit_users = st.multiselect(
                "Felhasználó", user_options, key="audit_filter_users"
            )
        with f2:
            action_options = sorted(x for x in audit_df["action"].dropna().astype(str).unique() if x)
            selected_audit_actions = st.multiselect(
                "Művelet", action_options, key="audit_filter_actions"
            )
        with f3:
            stat_options = sorted(x for x in audit_df["stat"].dropna().astype(str).unique() if x)
            selected_audit_stats = st.multiselect(
                "Statisztika", stat_options, key="audit_filter_stats"
            )

        search_audit = st.text_input(
            "Szöveges keresés a naplóban:",
            placeholder="pl. MiniCRM, Laura, 2026-10-15, törlés...",
            key="audit_text_search",
        )

        filtered_audit = audit_df.copy()
        if selected_audit_users:
            filtered_audit = filtered_audit[filtered_audit["user"].isin(selected_audit_users)]
        if selected_audit_actions:
            filtered_audit = filtered_audit[filtered_audit["action"].isin(selected_audit_actions)]
        if selected_audit_stats:
            filtered_audit = filtered_audit[filtered_audit["stat"].isin(selected_audit_stats)]
        if search_audit.strip():
            q = search_audit.casefold().strip()
            haystack = (
                filtered_audit["timestamp"].astype(str) + " "
                + filtered_audit["user"].astype(str) + " "
                + filtered_audit["action"].astype(str) + " "
                + filtered_audit["stat"].astype(str) + " "
                + filtered_audit["summary"].astype(str)
            ).str.casefold()
            filtered_audit = filtered_audit[haystack.str.contains(q, regex=False, na=False)]

        display_audit = filtered_audit.copy()
        display_audit["Időpont"] = display_audit["_ts"].apply(
            lambda x: x.strftime("%Y.%m.%d. %H:%M:%S") if pd.notna(x) else ""
        )
        display_audit = display_audit.rename(
            columns={
                "user": "Felhasználó",
                "action": "Művelet",
                "stat": "Statisztika",
                "summary": "Rövid leírás",
            }
        )
        st.caption(f"Találatok: {len(display_audit)}")
        st.dataframe(
            display_audit[["Időpont", "Felhasználó", "Művelet", "Statisztika", "Rövid leírás"]],
            use_container_width=True,
            hide_index=True,
        )

        st.markdown("### 🔍 Egy bejegyzés részletei")
        if not filtered_audit.empty:
            option_rows = filtered_audit.head(500).to_dict("records")
            option_map = {
                str(row.get("id", i)): (
                    f"{pd.to_datetime(row.get('timestamp'), errors='coerce').strftime('%Y.%m.%d. %H:%M:%S') if pd.notna(pd.to_datetime(row.get('timestamp'), errors='coerce')) else row.get('timestamp', '')}"
                    f" · {row.get('user', '')} · {row.get('action', '')}"
                    f" · {row.get('stat', '')}"
                )
                for i, row in enumerate(option_rows)
            }
            selected_event_id = st.selectbox(
                "Bejegyzés:",
                options=list(option_map.keys()),
                format_func=lambda x: option_map[x],
                key="audit_event_detail_select",
            )
            selected_event = next(
                (row for row in option_rows if str(row.get("id")) == selected_event_id),
                None,
            )
            if selected_event:
                st.json({k: v for k, v in selected_event.items() if k != "_ts"})

        st.markdown("### ⬇️ Napló export")
        export_rows = [
            {k: v for k, v in row.items() if k != "_ts"}
            for row in filtered_audit.to_dict("records")
        ]
        export_stamp = budapest_now().strftime("%Y-%m-%d_%H-%M-%S")
        ec1, ec2 = st.columns(2)
        with ec1:
            st.download_button(
                "⬇️ Szűrt napló CSV",
                data=display_audit[["Időpont", "Felhasználó", "Művelet", "Statisztika", "Rövid leírás"]]
                    .to_csv(index=False)
                    .encode("utf-8-sig"),
                file_name=f"SCART_tevekenysegi_naplo_{export_stamp}.csv",
                mime="text/csv",
                use_container_width=True,
            )
        with ec2:
            st.download_button(
                "⬇️ Szűrt napló JSON",
                data=json.dumps(export_rows, ensure_ascii=False, indent=2, default=str).encode("utf-8"),
                file_name=f"SCART_tevekenysegi_naplo_{export_stamp}.json",
                mime="application/json",
                use_container_width=True,
            )

# 6. BIZTONSÁGI MENTÉS (CSAK ADMIN)
elif selected_menu == "💾 Biztonsági mentés":
    st.title(f"💾 {SCART_NAME} – Biztonsági mentés")
    st.info(
        "Itt bármikor lementheted a SCART aktuális állapotát. A letöltés nem módosít "
        "és nem töröl semmilyen adatot. Streamlit Community Cloud használatakor érdemes "
        "minden nagyobb adatbevitel vagy programfrissítés előtt teljes mentést készíteni."
    )

    backup_stamp = budapest_now().strftime("%Y-%m-%d_%H-%M-%S")
    backup_db = copy.deepcopy(st.session_state.db)
    backup_users = copy.deepcopy(users_db)
    backup_archive = load_archive()
    backup_audit = load_audit()

    db_bytes = json.dumps(
        backup_db, ensure_ascii=False, indent=2
    ).encode("utf-8")
    users_bytes = json.dumps(
        backup_users, ensure_ascii=False, indent=2
    ).encode("utf-8")
    archive_bytes = json.dumps(
        backup_archive, ensure_ascii=False, indent=2
    ).encode("utf-8")
    audit_bytes = json.dumps(
        backup_audit, ensure_ascii=False, indent=2
    ).encode("utf-8")

    total_rows = sum(
        len(stat_obj.get("data", []))
        for stat_obj in backup_db.get("stats", {}).values()
        if isinstance(stat_obj, dict)
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Statisztikák", len(backup_db.get("stats", {})))
    c2.metric("Összes adatsor", total_rows)
    c3.metric("Felhasználók", len(backup_users))
    c4.metric("Naplóbejegyzések", len(backup_audit))

    backup_info = {
        "scart_version": SCART_VERSION,
        "created_at": budapest_now().isoformat(timespec="seconds"),
        "created_by": st.session_state.username,
        "statistics": len(backup_db.get("stats", {})),
        "data_rows": total_rows,
        "users": len(backup_users),
        "archived_statistics": len(backup_archive),
        "audit_entries": len(backup_audit),
    }

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("statisztikak.json", db_bytes)
        zf.writestr("users.json", users_bytes)
        zf.writestr("archivum.json", archive_bytes)
        zf.writestr("tevekenysegi_naplo.json", audit_bytes)
        zf.writestr(
            "backup_info.json",
            json.dumps(backup_info, ensure_ascii=False, indent=2).encode("utf-8"),
        )

    st.markdown("### 📦 Teljes SCART mentés")
    st.download_button(
        "⬇️ Teljes biztonsági mentés letöltése (.zip)",
        data=zip_buffer.getvalue(),
        file_name=f"SCART_teljes_backup_{backup_stamp}.zip",
        mime="application/zip",
        type="primary",
        use_container_width=True,
        key="download_full_scart_backup",
    )
    st.caption(
        "A ZIP tartalmazza a statisztikákat, az archívumot, a tevékenységi naplót és a felhasználói adatbázist is. "
        "A users.json jogosultsági adatokat és jelszó-hasheket tartalmaz, ezért a teljes mentést "
        "bizalmas fájlként kezeld."
    )

    st.markdown("### 📄 Külön fájlok")
    col_b1, col_b2, col_b3, col_b4 = st.columns(4)
    with col_b1:
        st.download_button(
            "📊 statisztikak.json",
            data=db_bytes,
            file_name=f"statisztikak_{backup_stamp}.json",
            mime="application/json",
            use_container_width=True,
            key="download_statistics_backup",
        )
    with col_b2:
        st.download_button(
            "👥 users.json",
            data=users_bytes,
            file_name=f"users_{backup_stamp}.json",
            mime="application/json",
            use_container_width=True,
            key="download_users_backup",
        )
    with col_b3:
        st.download_button(
            "📂 archivum.json",
            data=archive_bytes,
            file_name=f"archivum_{backup_stamp}.json",
            mime="application/json",
            use_container_width=True,
            key="download_archive_backup",
        )
    with col_b4:
        st.download_button(
            "📖 tevekenysegi_naplo.json",
            data=audit_bytes,
            file_name=f"tevekenysegi_naplo_{backup_stamp}.json",
            mime="application/json",
            use_container_width=True,
            key="download_audit_backup",
        )

    st.success(
        "✅ A biztonsági mentés mindig a jelenleg betöltött, aktuális SCART-adatokat tartalmazza."
    )

# 7. ADMINISZTRÁCIÓ & ARCHÍVUM (CSAK ADMIN)
elif selected_menu == "⚙️ Adminisztráció & Archívum":
    st.title(f"⚙️ {SCART_NAME} – Adminisztráció")

    # --- 1. MEGLÉVŐ STATISZTIKÁK LEÍRÁSÁNAK / BEÁLLÍTÁSAINAK MÓDOSÍTÁSA ---
    st.subheader("✏️ Statisztika Beállítások & Leírás Módosítása")
    selected_edit_stat = st.selectbox(
        "Válassz statisztikát a módosításhoz:",
        options=all_stat_names,
        format_func=stat_label,
        key="admin_edit_stat_select",
    )

    if selected_edit_stat:
        curr_stat_obj = st.session_state.db["stats"][selected_edit_stat]
        with st.form("edit_stat_info_form"):
            updated_group = st.selectbox(
                "Csoport / Részleg:",
                options=all_groups,
                index=all_groups.index(curr_stat_obj.get("group", all_groups[0]))
                if curr_stat_obj.get("group") in all_groups
                else 0,
            )
            updated_unit = st.text_input(
                "Mértékegység:", value=curr_stat_obj.get("unit", "")
            )
            updated_desc = st.text_area(
                "Leírás / Útmutató (mit kell ide rögzíteni):",
                value=curr_stat_obj.get("description", ""),
            )
            updated_inverted = st.checkbox(
                "Fordított statisztika (a 0 felül van)",
                value=curr_stat_obj.get("inverted", False),
            )

            save_stat_info_btn = st.form_submit_button(
                "💾 Statisztika Adatainak Mentése"
            )
            if save_stat_info_btn:
                st.session_state.db["stats"][selected_edit_stat][
                    "group"
                ] = updated_group
                st.session_state.db["stats"][selected_edit_stat]["unit"] = updated_unit
                st.session_state.db["stats"][selected_edit_stat][
                    "description"
                ] = updated_desc
                st.session_state.db["stats"][selected_edit_stat][
                    "inverted"
                ] = updated_inverted
                save_data(st.session_state.db)
                append_audit_event(
                    "Statisztika adatainak módosítása",
                    stat_name=selected_edit_stat,
                    summary=f"'{selected_edit_stat}' alapadatai módosítva",
                    details={
                        "group": updated_group,
                        "unit": updated_unit,
                        "description": updated_desc,
                        "inverted": updated_inverted,
                    },
                )
                st.success(f"'{selected_edit_stat}' beállításai frissítve!")
                st.rerun()

    st.markdown("---")

    # --- 2. FELHASZNÁLÓK ÉS JOGOSULTSÁGOK KEZELÉSE ---
    st.subheader("👥 Felhasználók & Jogosultságok Kezelése")

    col_u_add, col_u_edit = st.columns(2)

    with col_u_add:
        st.markdown("#### ➕ Új Felhasználó Hozzáadása")
        with st.form("add_user_form", clear_on_submit=True):
            new_username = st.text_input("Felhasználónév:")
            new_password = st.text_input("Jelszó:", type="password")
            new_role = st.selectbox(
                "Jogosultság:",
                ["user", "admin"],
                format_func=lambda x: "👑 Admin" if x == "admin" else "👤 Sima felhasználó",
            )
            assigned_stats_for_new = st.multiselect(
                "Hozzárendelt Egyedi Statisztikák:",
                options=all_stat_names,
                format_func=stat_label,
            )
            assigned_groups_for_new = st.multiselect(
                "Hozzárendelt Egész Csoportok / Részlegek:", options=all_groups
            )

            add_user_btn = st.form_submit_button("Felhasználó Létrehozása")
            if add_user_btn:
                if new_username and new_password:
                    if new_username in users_db:
                        st.error("Ez a felhasználónév már létezik!")
                    else:
                        users_db[new_username] = {
                            "password": hash_password(new_password),
                            "role": new_role,
                            "assigned_stats": assigned_stats_for_new,
                            "assigned_groups": assigned_groups_for_new,
                            "auth_version": 1,
                        }
                        save_users(users_db)
                        append_audit_event(
                            "Felhasználó létrehozása",
                            summary=f"Új felhasználó létrehozva: {new_username}",
                            details={
                                "username": new_username,
                                "role": new_role,
                                "assigned_stats": assigned_stats_for_new,
                                "assigned_groups": assigned_groups_for_new,
                            },
                        )
                        st.success(f"'{new_username}' felhasználó sikeresen létrehozva!")
                        st.rerun()
                else:
                    st.warning("A felhasználónév és jelszó megadása kötelező!")

    with col_u_edit:
        st.markdown("#### ✏️ Meglévő Felhasználó Módosítása")
        selected_edit_user = st.selectbox(
            "Válassz felhasználót:", options=list(users_db.keys())
        )

        if selected_edit_user:
            u_data = users_db[selected_edit_user]
            with st.form("edit_user_form"):
                updated_pass = st.text_input(
                    "Új Jelszó (hagyja üresen ha nem változik):", type="password"
                )
                updated_role = st.selectbox(
                    "Jogosultság módosítása:",
                    ["user", "admin"],
                    index=0 if u_data.get("role", "user") == "user" else 1,
                    format_func=lambda x: (
                        "👑 Admin" if x == "admin" else "👤 Sima felhasználó"
                    ),
                )
                updated_assigned_stats = st.multiselect(
                    "Hozzárendelt Egyedi Statisztikák Módosítása:",
                    options=all_stat_names,
                    default=[
                        s
                        for s in u_data.get("assigned_stats", [])
                        if s in all_stat_names
                    ],
                    format_func=stat_label,
                )
                updated_assigned_groups = st.multiselect(
                    "Hozzárendelt Egész Csoportok / Részlegek Módosítása:",
                    options=all_groups,
                    default=[
                        g for g in u_data.get("assigned_groups", []) if g in all_groups
                    ],
                )

                save_u_edit = st.form_submit_button("💾 Módosítások Mentése")
                if save_u_edit:
                    admin_count = sum(
                        1 for user_obj in users_db.values() if user_obj.get("role") == "admin"
                    )
                    removing_last_admin = (
                        u_data.get("role") == "admin"
                        and updated_role != "admin"
                        and admin_count <= 1
                    )
                    if removing_last_admin:
                        st.error("Az utolsó adminisztrátor jogosultsága nem vehető el.")
                    else:
                        old_user_audit = {
                            "role": users_db[selected_edit_user].get("role", "user"),
                            "assigned_stats": list(users_db[selected_edit_user].get("assigned_stats", [])),
                            "assigned_groups": list(users_db[selected_edit_user].get("assigned_groups", [])),
                        }
                        if updated_pass:
                            users_db[selected_edit_user]["password"] = hash_password(updated_pass)
                        users_db[selected_edit_user]["role"] = updated_role
                        users_db[selected_edit_user]["assigned_stats"] = updated_assigned_stats
                        users_db[selected_edit_user]["assigned_groups"] = updated_assigned_groups
                        users_db[selected_edit_user]["auth_version"] = int(
                            users_db[selected_edit_user].get("auth_version", 1)
                        ) + 1
                        save_users(users_db)
                        if selected_edit_user == st.session_state.username:
                            st.session_state.auth_version = users_db[selected_edit_user]["auth_version"]
                        append_audit_event(
                            "Felhasználó módosítása",
                            summary=f"Felhasználói jogosultságok módosítva: {selected_edit_user}",
                            details={
                                "username": selected_edit_user,
                                "before": old_user_audit,
                                "after": {
                                    "role": updated_role,
                                    "assigned_stats": updated_assigned_stats,
                                    "assigned_groups": updated_assigned_groups,
                                },
                                "password_changed": bool(updated_pass),
                            },
                        )
                        st.success(f"'{selected_edit_user}' adatai frissítve!")
                        st.rerun()

    st.markdown("---")

    # --- 3. STATISZTIKA MEGERŐSÍTÉSES TÖRLESE ---
    st.subheader("🗑️ Statisztika kategória végleges törlése")
    stat_to_delete_cat = st.selectbox(
        "Törlendő statisztika kategória:",
        options=[""] + all_stat_names,
        format_func=lambda x: stat_label(x) if x else "",
        key="stat_del_select",
    )

    if "confirm_delete_stat" not in st.session_state:
        st.session_state.confirm_delete_stat = None

    if st.button("🗑️ Törlési Folyamat Indítása") and stat_to_delete_cat:
        st.session_state.confirm_delete_stat = stat_to_delete_cat

    if (
        st.session_state.confirm_delete_stat
        and st.session_state.confirm_delete_stat == stat_to_delete_cat
    ):
        st.warning(
            f"⚠️ **BIZTOSAN TÖRÖLNI AKAROD A(Z) '{stat_to_delete_cat}'"
            " STATISZTIKÁT?**\nEz a művelet végleges és az összes adat elveszik!"
        )
        col_confirm1, col_confirm2 = st.columns(2)
        with col_confirm1:
            if st.button("✅ Igen, biztosan törlöm véglegesen", type="primary"):
                target = st.session_state.confirm_delete_stat
                if target in st.session_state.db["stats"]:
                    deleted_stat_snapshot = copy.deepcopy(st.session_state.db["stats"][target])
                    del st.session_state.db["stats"][target]
                    if (
                        "settings" in st.session_state.db
                        and target in st.session_state.db["settings"]
                    ):
                        del st.session_state.db["settings"][target]
                    save_data(st.session_state.db)

                    # Törlés a felhasználói hozzárendelésekből is
                    for u_k in users_db:
                        if target in users_db[u_k].get("assigned_stats", []):
                            users_db[u_k]["assigned_stats"].remove(target)
                            users_db[u_k]["auth_version"] = int(users_db[u_k].get("auth_version", 1)) + 1
                    save_users(users_db)
                    append_audit_event(
                        "Statisztika végleges törlése",
                        stat_name=target,
                        summary=f"Statisztika véglegesen törölve: {target}",
                        details={
                            "group": deleted_stat_snapshot.get("group", ""),
                            "unit": deleted_stat_snapshot.get("unit", ""),
                            "deleted_rows": len(deleted_stat_snapshot.get("data", [])),
                        },
                    )

                    st.session_state.confirm_delete_stat = None
                    st.success(f"'{target}' sikeresen törölve!")
                    st.rerun()

        with col_confirm2:
            if st.button("❌ Mégse, mégsem törlöm"):
                st.session_state.confirm_delete_stat = None
                st.rerun()

    st.markdown("---")

    # --- 4. CSOPORTOK KEZELÉSE ---
    st.subheader("📁 Csoportok / Részlegek Kezelése")
    col_g1, col_g2 = st.columns(2)
    with col_g1:
        new_group_name = st.text_input("Új részleg / csoport neve:")
        if st.button("➕ Részleg Hozzáadása"):
            if (
                new_group_name
                and new_group_name not in st.session_state.db["groups"]
            ):
                st.session_state.db["groups"].append(new_group_name)
                save_data(st.session_state.db)
                append_audit_event(
                    "Részleg létrehozása",
                    summary=f"Új részleg létrehozva: {new_group_name}",
                    details={"group": new_group_name},
                )
                st.success(f"'{new_group_name}' sikeresen létrehozva!")
                st.rerun()
            else:
                st.warning("Add meg a nevet vagy már létezik ilyen részleg!")

    with col_g2:
        current_groups_list = db.get("groups", [])
        group_to_delete = st.selectbox(
            "Törlendő részleg:",
            options=current_groups_list if current_groups_list else [""],
        )
        if st.button("🗑️ Részleg Törlése") and group_to_delete:
            if group_to_delete in st.session_state.db["groups"]:
                st.session_state.db["groups"].remove(group_to_delete)
                for s_key in st.session_state.db["stats"]:
                    if st.session_state.db["stats"][s_key].get("group") == group_to_delete:
                        st.session_state.db["stats"][s_key]["group"] = "Egyéb"
                if "Egyéb" not in st.session_state.db["groups"]:
                    st.session_state.db["groups"].append("Egyéb")
                save_data(st.session_state.db)

                for u_k in users_db:
                    if group_to_delete in users_db[u_k].get("assigned_groups", []):
                        users_db[u_k]["assigned_groups"].remove(group_to_delete)
                        users_db[u_k]["auth_version"] = int(users_db[u_k].get("auth_version", 1)) + 1
                save_users(users_db)
                append_audit_event(
                    "Részleg törlése",
                    summary=f"Részleg törölve: {group_to_delete}",
                    details={"group": group_to_delete},
                )

                st.success(f"'{group_to_delete}' részleg törölve!")
                st.rerun()

    st.markdown("---")

    # --- 5. ARCHÍVUM KEZELÉSE ---
    st.subheader("📂 Archívum kezelése")
    archive_db = load_archive()

    col_a1, col_a2 = st.columns(2)
    with col_a1:
        st.markdown("#### Statisztika archiválása")
        stat_to_archive = st.selectbox(
            "Archiválandó statisztika:",
            options=all_stat_names,
            format_func=stat_label,
        )
        if st.button("📦 Archiválás"):
            if stat_to_archive in archive_db:
                st.warning("Ebből a statisztikából már van archív példány. Előbb állítsd vissza vagy kezeld a meglévőt.")
            else:
                archive_db[stat_to_archive] = {
                    "stat": copy.deepcopy(db["stats"][stat_to_archive]),
                    "settings": copy.deepcopy(db.get("settings", {}).get(stat_to_archive, {})),
                    "archived_at": budapest_now().isoformat(timespec="seconds"),
                    "archived_by": st.session_state.username,
                }
                # Először az archív példány készül el; csak utána kerül ki az aktív listából.
                save_archive(archive_db)
                del st.session_state.db["stats"][stat_to_archive]
                st.session_state.db.get("settings", {}).pop(stat_to_archive, None)
                save_data(st.session_state.db)
                append_audit_event(
                    "Statisztika archiválása",
                    stat_name=stat_to_archive,
                    summary=f"Statisztika archiválva: {stat_to_archive}",
                    details={
                        "rows": len(archive_db[stat_to_archive].get("stat", {}).get("data", []))
                    },
                )
                st.success("A statisztika archiválva és az aktív listából eltávolítva.")
                st.rerun()

    with col_a2:
        st.markdown("#### Visszaállítás az archívumból")
        if archive_db:
            stat_to_restore = st.selectbox(
                "Visszaállítandó elem:",
                options=list(archive_db.keys()),
                format_func=stat_label,
            )
            if st.button("🔄 Visszaállítás"):
                if stat_to_restore in st.session_state.db["stats"]:
                    st.error("Azonos nevű aktív statisztika már létezik; a SCART nem írja felül.")
                else:
                    archived_payload = archive_db[stat_to_restore]
                    if isinstance(archived_payload, dict) and "stat" in archived_payload:
                        stat_payload = archived_payload["stat"]
                        settings_payload = archived_payload.get("settings", {})
                    else:
                        # Korábbi SCART/Statisztika Rendszer archívum formátuma.
                        stat_payload = archived_payload
                        settings_payload = {}
                    st.session_state.db["stats"][stat_to_restore] = copy.deepcopy(stat_payload)
                    if settings_payload:
                        st.session_state.db.setdefault("settings", {})[stat_to_restore] = copy.deepcopy(settings_payload)
                    save_data(st.session_state.db)
                    del archive_db[stat_to_restore]
                    save_archive(archive_db)
                    append_audit_event(
                        "Statisztika visszaállítása",
                        stat_name=stat_to_restore,
                        summary=f"Statisztika visszaállítva az archívumból: {stat_to_restore}",
                        details={"rows": len(stat_payload.get("data", [])) if isinstance(stat_payload, dict) else 0},
                    )
                    st.success("Visszaállítva és az archívumból eltávolítva!")
                    st.rerun()
        else:
            st.info("Az archívum üres.")
