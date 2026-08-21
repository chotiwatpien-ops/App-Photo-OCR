# -*- coding: utf-8 -*-
"""Excel output in the team's template layout ("Template Riders Project 2026.xlsx").

Sheet1  — exactly the team's 17 columns A..Q, same header style, formulas J =K+M+N and Q =P-J
Analysis — one row per trip with the extra fields the screenshots give us (booking code,
           districts, full addresses, surge, fees…) so nothing is lost but Sheet1 stays clean

* build_workbook(rows) -> bytes   : on-demand export (cloud, ingest weekly file)
* append_trips(...)                : local mode, appends to the app-owned workbook
"""
import io
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

import config
from zones import zone_for

SHEET = "Sheet1"
ANALYSIS_SHEET = "Analysis"

HEADERS = [
    "Driver Name", "Date & Time", "Time", "Service Type", "Payment Method",
    "Pick-up Location", "Drop-off Location", "Distance (km)", "Duration (mins)",
    "Net Earnings (THB)", "Base Fare (THB)", "International Fee", "Bonus",
    "Turbo Incentive (THB)", "Reimbursements / Tolls (THB)",
    "Passenger Fare (THB)", "Grab Service Fee (THB)",
]
COL_WIDTHS = [11.4, 9.7, 12.9, 12.5, 13.5, 12.5, 13.4, 10.5, 12.0, 14.1, 11.9, 13.2, 7.8, 16.4, 22.3, 15.9, 17.1]

ANALYSIS_HEADERS = [
    "Driver Name", "Date", "Time", "Booking Code", "Week", "Pick-up Zone", "Drop-off Zone",
    "Pick-up District", "Drop-off District", "Pick-up Province", "Drop-off Province",
    "Pick-up Address", "Drop-off Address", "Surge", "Queue Type", "Stops",
    "App Fee (THB)", "Other Adjustments (THB)", "Fare Refund (THB)",
    "Check", "Approved By", "Source File",
]
ANALYSIS_WIDTHS = [24, 11, 7, 16, 6, 12, 12, 14, 14, 9, 9, 36, 36, 6, 11, 6, 10, 12, 12, 8, 11, 22]

# --- template styling (copied from the team's file) ---
_MED = Side(style="medium", color="000000")
_BORDER = Border(left=_MED, right=_MED, top=_MED, bottom=_MED)
_HEAD_FONT = Font(name="Calibri", bold=True, color="FFFFFFFF", size=9)
_HEAD_FILL = PatternFill("solid", fgColor="FF3C78D8")
_BODY_FONT = Font(name="Arial", size=10)
_THIN = Side(style="thin", color="BFBFBF")
_THIN_BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)


class ExcelLockedError(Exception):
    pass


# ---------- shared ----------

def _parse_time(s):
    if not s:
        return None
    try:
        return datetime.strptime(s.strip(), "%H:%M").time()
    except ValueError:
        return None


def _style_header(ws, headers, widths, medium=True):
    for c, h in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=c)
        cell.value = h
        cell.font, cell.fill = _HEAD_FONT, _HEAD_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = _BORDER if medium else _THIN_BORDER
        ws.column_dimensions[get_column_letter(c)].width = widths[c - 1]
    ws.row_dimensions[1].height = 14.4


def _write_main_row(ws, row, driver_name, t):
    d = datetime.strptime(t["trip_date"], "%Y-%m-%d")
    values = [
        driver_name,                                            # A
        d,                                                      # B Date & Time
        _parse_time(t.get("trip_time")),                        # C
        t.get("service_type"),                                  # D
        t.get("payment_method"),                                # E
        zone_for(t.get("pickup_district"), t.get("pickup_code"), t.get("pickup_text")),    # F
        zone_for(t.get("dropoff_district"), t.get("dropoff_code"), t.get("dropoff_text")),  # G
        t.get("distance_km"),                                   # H
        t.get("duration_mins"),                                 # I
        f"=K{row}+M{row}+N{row}",                               # J net (template formula)
        t.get("base_fare"),                                     # K
        t.get("intl_fee") or 0,                                 # L
        t.get("bonus") or 0,                                    # M
        t.get("turbo") or 0,                                    # N
        t.get("tolls") or 0,                                    # O
        t.get("passenger_total"),                               # P
        f"=P{row}-J{row}" if t.get("passenger_total") is not None else None,  # Q (template formula)
    ]
    for col, v in enumerate(values, start=1):
        cell = ws.cell(row=row, column=col)
        cell.value = v  # explicit assign — ws.cell(value=None) would NOT clear a cell
        cell.font = _BODY_FONT
        cell.border = _BORDER
        if col == 2:
            cell.number_format = "d-mmm-yy"
        elif col == 3 and v is not None:
            cell.number_format = "HH:MM"


def _write_analysis_row(ws, row, driver_name, t):
    d = datetime.strptime(t["trip_date"], "%Y-%m-%d")
    values = [
        driver_name, d, _parse_time(t.get("trip_time")), t.get("booking_code"),
        f"=ISOWEEKNUM(B{row})",
        zone_for(t.get("pickup_district"), t.get("pickup_code"), t.get("pickup_text")),
        zone_for(t.get("dropoff_district"), t.get("dropoff_code"), t.get("dropoff_text")),
        t.get("pickup_district"), t.get("dropoff_district"),
        t.get("pickup_code"), t.get("dropoff_code"),
        t.get("pickup_text"), t.get("dropoff_text"),
        "Y" if t.get("surge") else None, t.get("queue_type"), t.get("num_stops"),
        t.get("app_fee"), t.get("other_adj"), t.get("fare_refund"),
        t.get("check_status"),
        "auto" if t.get("auto_approved") else ("person" if t.get("committed") else "pending"),
        t.get("file_name"),
    ]
    for col, v in enumerate(values, start=1):
        cell = ws.cell(row=row, column=col)
        cell.value = v
        cell.font = _BODY_FONT
        cell.border = _THIN_BORDER
        if col == 2:
            cell.number_format = "d-mmm-yy"
        elif col == 3 and v is not None:
            cell.number_format = "HH:MM"


def _new_workbook():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = SHEET
    _style_header(ws, HEADERS, COL_WIDTHS, medium=True)
    wa = wb.create_sheet(ANALYSIS_SHEET)
    _style_header(wa, ANALYSIS_HEADERS, ANALYSIS_WIDTHS, medium=False)
    wa.freeze_panes = "A2"
    return wb


# ---------- export (cloud + local) ----------

def build_workbook(rows: list[dict]) -> bytes:
    """Rows from db.query_trips (each carries driver_name). Returns xlsx bytes."""
    wb = _new_workbook()
    ws, wa = wb[SHEET], wb[ANALYSIS_SHEET]
    for i, t in enumerate(rows, start=2):
        _write_main_row(ws, i, t["driver_name"], t)
        _write_analysis_row(wa, i, t["driver_name"], t)
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
        _new_workbook().save(config.EXCEL_PATH)
    try:
        wb = openpyxl.load_workbook(config.EXCEL_PATH)
    except PermissionError as e:
        raise ExcelLockedError(str(e)) from e
    if SHEET not in wb.sheetnames:  # a file from the older single-sheet layout
        wb.active.title = SHEET
    ws = wb[SHEET]
    if any(ws.cell(row=1, column=c).value != h for c, h in enumerate(HEADERS, start=1)):
        _style_header(ws, HEADERS, COL_WIDTHS, medium=True)
    if ANALYSIS_SHEET not in wb.sheetnames:
        wa = wb.create_sheet(ANALYSIS_SHEET)
        _style_header(wa, ANALYSIS_HEADERS, ANALYSIS_WIDTHS, medium=False)
        wa.freeze_panes = "A2"
    return wb


def _load_readonly():
    if not config.EXCEL_PATH.exists():
        return None
    try:
        return openpyxl.load_workbook(config.EXCEL_PATH, read_only=True)
    except PermissionError:
        return openpyxl.load_workbook(_snapshot_copy(), read_only=True)


def _next_row(ws):
    row = ws.max_row + 1
    while row > 2 and ws.cell(row=row - 1, column=1).value in (None, ""):
        row -= 1
    return row


def count_existing_rows(driver_name: str, dates: set[str]) -> int:
    """How many rows already in the local workbook for this driver within these dates."""
    wb = _load_readonly()
    if wb is None or SHEET not in wb.sheetnames:
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
    """Appends rows to the local workbook (both sheets); raises ExcelLockedError if Excel has it open."""
    wb = _load_for_write()
    ws, wa = wb[SHEET], wb[ANALYSIS_SHEET]
    r1, r2 = _next_row(ws), _next_row(wa)
    for t in trips:
        _write_main_row(ws, r1, driver_name, t)
        _write_analysis_row(wa, r2, driver_name, t)
        r1 += 1
        r2 += 1
    try:
        wb.save(config.EXCEL_PATH)
    except PermissionError as e:
        raise ExcelLockedError(str(e)) from e
    return len(trips)
