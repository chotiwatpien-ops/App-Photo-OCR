# -*- coding: utf-8 -*-
"""Excel output — one layout, two uses:

* build_workbook(rows)  -> bytes   : on-demand export (cloud and local)
* append_trips(...)                : local mode only, appends to the app-owned workbook

Layout:
A Driver Name | B Date | C Time | D Service Type | E Payment Method
F Pick-up | G Drop-off | H Distance (km) | I Duration (mins)
J Net Earnings (THB) =K+M+N (FORMULA) | K Base Fare (THB) | L International Fee
M Bonus | N Turbo Incentive (THB) | O Reimbursements / Tolls (THB)
P Passenger Fare (THB) | Q Grab Service Fee (THB) =P-K (FORMULA)
R Week =ISOWEEKNUM(B) (FORMULA) | S Booking Code
T Pick-up District | U Drop-off District | V Pick-up Address | W Drop-off Address
X Surge (Y/blank) | Y Queue Type | Z Stops | AA App Fee (THB)
AB Other Adjustments (THB) | AC Fare Refund (THB)
"""
import io
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

import config

SHEET = "Trips"
HEADERS = [
    "Driver Name", "Date", "Time", "Service Type", "Payment Method",
    "Pick-up Location", "Drop-off Location", "Distance (km)", "Duration (mins)",
    "Net Earnings (THB)", "Base Fare (THB)", "International Fee", "Bonus",
    "Turbo Incentive (THB)", "Reimbursements / Tolls (THB)",
    "Passenger Fare (THB)", "Grab Service Fee (THB)", "Week", "Booking Code",
    "Pick-up District", "Drop-off District", "Pick-up Address", "Drop-off Address",
    "Surge", "Queue Type", "Stops", "App Fee (THB)", "Other Adjustments (THB)",
    "Fare Refund (THB)",
]
COL_WIDTHS = [24, 12, 8, 14, 14, 10, 10, 12, 13, 16, 14, 13, 8, 13, 13, 15, 15, 7, 16,
              15, 15, 36, 36, 7, 11, 6, 11, 13, 13]
_HEAD_FONT = Font(name="Arial", bold=True, color="FFFFFF", size=10)
_HEAD_FILL = PatternFill("solid", fgColor="1F3864")
_BODY_FONT = Font(name="Arial", size=10)


class ExcelLockedError(Exception):
    pass


# ---------- shared row builder ----------

def _parse_time(s):
    if not s:
        return None
    try:
        return datetime.strptime(s.strip(), "%H:%M").time()
    except ValueError:
        return None


def _style_header(ws):
    for c, h in enumerate(HEADERS, start=1):
        cell = ws.cell(row=1, column=c)
        cell.value = h
        cell.font, cell.fill = _HEAD_FONT, _HEAD_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center")
        ws.column_dimensions[get_column_letter(c)].width = COL_WIDTHS[c - 1]
    ws.freeze_panes = "A2"


def _write_row(ws, row: int, driver_name: str, t: dict):
    d = datetime.strptime(t["trip_date"], "%Y-%m-%d")
    pt = t.get("passenger_total")
    values = [
        driver_name, d, _parse_time(t.get("trip_time")),
        t.get("service_type"), t.get("payment_method"),
        t.get("pickup_code"), t.get("dropoff_code"),
        t.get("distance_km"), t.get("duration_mins"),
        f"=K{row}+M{row}+N{row}",
        t.get("base_fare"), t.get("intl_fee") or 0, t.get("bonus") or 0,
        t.get("turbo") or 0, t.get("tolls") or 0,
        pt, f"=P{row}-K{row}" if pt is not None else None,
        f"=ISOWEEKNUM(B{row})", t.get("booking_code"),
        t.get("pickup_district"), t.get("dropoff_district"),
        t.get("pickup_text"), t.get("dropoff_text"),
        "Y" if t.get("surge") else None, t.get("queue_type"), t.get("num_stops"),
        t.get("app_fee"), t.get("other_adj"), t.get("fare_refund"),
    ]
    for col, v in enumerate(values, start=1):
        cell = ws.cell(row=row, column=col)
        cell.value = v  # explicit assign — ws.cell(value=None) would NOT clear a cell
        cell.font = _BODY_FONT
        if col == 2:
            cell.number_format = "DD/MM/YYYY"
        elif col == 3 and v is not None:
            cell.number_format = "HH:MM"


# ---------- export (cloud + local) ----------

def build_workbook(rows: list[dict]) -> bytes:
    """Rows from db.query_trips (each carries driver_name). Returns xlsx bytes."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = SHEET
    _style_header(ws)
    for i, t in enumerate(rows, start=2):
        _write_row(ws, i, t["driver_name"], t)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------- local append mode ----------

def _snapshot_copy() -> Path:
    """Copy the workbook even while Excel holds it open (Windows: PowerShell can, Python can't)."""
    if sys.platform != "win32":
        raise ExcelLockedError("workbook is locked")
    tmp = Path(tempfile.gettempdir()) / "rider_trips_snapshot.xlsx"
    subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         f'Copy-Item -LiteralPath "{config.EXCEL_PATH}" -Destination "{tmp}" -Force'],
        check=True, capture_output=True, timeout=30,
    )
    return tmp


def _load_for_write():
    if not config.EXCEL_PATH.exists():
        wb = openpyxl.Workbook()
        wb.active.title = SHEET
        _style_header(wb.active)
        wb.save(config.EXCEL_PATH)
    try:
        wb = openpyxl.load_workbook(config.EXCEL_PATH)
    except PermissionError as e:
        raise ExcelLockedError(str(e)) from e
    ws = wb[SHEET]
    if any(ws.cell(row=1, column=c).value != h for c, h in enumerate(HEADERS, start=1)):
        _style_header(ws)  # upgrade older files that lack newer columns
    return wb


def _load_readonly():
    if not config.EXCEL_PATH.exists():
        return None
    try:
        return openpyxl.load_workbook(config.EXCEL_PATH, read_only=True)
    except PermissionError:
        return openpyxl.load_workbook(_snapshot_copy(), read_only=True)


def count_existing_rows(driver_name: str, dates: set[str]) -> int:
    """How many rows already in the local workbook for this driver within these dates."""
    wb = _load_readonly()
    if wb is None:
        return 0
    n = 0
    for r in wb[SHEET].iter_rows(min_row=2, max_col=2, values_only=True):
        if r[0] and str(r[0]).strip() == driver_name.strip():
            d = r[1]
            if isinstance(d, datetime) and d.strftime("%Y-%m-%d") in dates:
                n += 1
    wb.close()
    return n


def append_trips(driver_name: str, trips: list[dict]) -> int:
    """Appends rows to the local workbook; raises ExcelLockedError if Excel has it open."""
    wb = _load_for_write()
    ws = wb[SHEET]
    row = ws.max_row + 1
    while row > 2 and ws.cell(row=row - 1, column=1).value in (None, ""):
        row -= 1
    for t in trips:
        _write_row(ws, row, driver_name, t)
        row += 1
    try:
        wb.save(config.EXCEL_PATH)
    except PermissionError as e:
        raise ExcelLockedError(str(e)) from e
    return len(trips)
