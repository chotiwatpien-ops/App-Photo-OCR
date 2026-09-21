# -*- coding: utf-8 -*-
"""Excel output in the team's template layout ("Template Riders Project 2026.xlsx").

Sheet1  — exactly the team's 17 columns A..Q, same header style, formulas J =K+M+N and Q =P-K
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
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.utils import get_column_letter

import config
from zones import zone_for

SHEET = "Sheet1"
ANALYSIS_SHEET = "Analysis"
LOCATION_FILE = "Rider Trips Phase 2.xlsx"
LOCATION_SHEET = "Location"
# Ops 2026-09-05 asked for the real pick-up and drop-off. Sheet1's own columns hold a zone that
# said "Downtown" for 84% of rows, but rewriting them would change three weeks already delivered
# and break whatever the customer pivots on — so the places go in a workbook of their own,
# 'Phase 2' in the name so nobody confuses it with the file the customer already has.
# Only from W36, the first week read with the addresses switched back on: W35 was read with the
# field off for 1,271 of its rows, and half a week of places is worse than none.
LOCATION_FROM_WEEK = str(getattr(config, "LOCATION_FROM_WEEK", "2026-W36"))
# Ops 2026-09-21 (Joe DMK) asked for every line of the passenger's fare block, and a name for the
# fare that stops people confusing it with what the passenger paid: "ride fare". That moves
# columns from L on, and flips L's sign to match the slip — a different sheet, not the same one
# with columns inserted. So, as at W36, a file of its own from the first week it applies to:
# W38, not yet delivered when this was decided. Phase 2 stops the week before and keeps its look.
FARE_LINES_FROM_WEEK = "2026-W38"
FARE_LINES_FILE = "Rider Trips Phase 3.xlsx"

# Bump whenever the shape of either workbook changes — columns, sheets, which rows go where.
# Uploads are skipped when no row has changed since the last round, which is right for data and
# wrong for layout: the Phase 2 file would have kept its old columns until the next approval
# happened to come along. Folding this into that fingerprint forces exactly one rewrite.
LAYOUT = "2026-09-21"

HEADERS = [
    "Driver Name", "Date & Time", "Time", "Service Type", "Payment Method",
    "Pick-up Location", "Drop-off Location", "Distance (km)", "Duration (mins)",
    "Net Earnings (THB)", "Base Fare (THB)", "International Fee", "Bonus",
    "Turbo Incentive (THB)", "Reimbursements / Tolls (THB)",
    "Passenger Fare (THB)", "Grab Service Fee (THB)", "Image",
]
COL_WIDTHS = [11.4, 9.7, 12.9, 12.5, 13.5, 12.5, 13.4, 10.5, 12.0, 14.1, 11.9, 13.2, 7.8, 16.4, 22.3, 15.9, 17.1, 18]

# Ops 2026-09-16 asked for the zone back, alongside the address: the address answers "where was
# this trip", the zone answers "how does the week split". They go AFTER the last column of the
# template, never between: Sheet1's own J and Q are formulas written with fixed letters
# (=K+M+N, =P-K), and inserting a column in the middle would point them at the wrong cells.
LOCATION_EXTRA = ["Pick-up Zone", "Drop-off Zone"]
LOCATION_HEADERS = HEADERS + LOCATION_EXTRA

# Phase 3 (from FARE_LINES_FROM_WEEK). A–O as the customer knows them, except that L is printed
# as the slip prints it (negative) and M no longer carries the tip. Then the passenger's block in
# slip order, each line its own column, signs as printed — so a reader can check any row:
#     V + L + Q + R + S + T + U − P = W          (paid + every line − the tip = the ride fare)
FARE_HEADERS = [
    "Driver Name", "Date & Time", "Time", "Service Type", "Payment Method",
    "Pick-up Location", "Drop-off Location", "Distance (km)", "Duration (mins)",
    "Net Earnings (THB)", "Base Fare (THB)", "International Fee", "Bonus",
    "Turbo Incentive (THB)", "Reimbursements / Tolls (THB)", "Tip (THB)",
    "Application Fee", "Discount", "Travel Insurance Fee", "Passenger Tolls", "Other Fees",
    "Passenger Fare (THB)", "Ride Fare (THB)", "Grab Service Fee (THB)", "Image",
]
FARE_WIDTHS = [11.4, 9.7, 12.9, 12.5, 13.5, 46, 46, 10.5, 12.0, 14.1, 11.9, 13.2, 7.8, 16.4, 22.3,
               9.5, 13.5, 10.5, 16.5, 14.5, 11.5, 15.9, 13.5, 17.1, 18]
FARE_LINES_HEADERS = FARE_HEADERS + LOCATION_EXTRA
_FARE_COL = {h: i for i, h in enumerate(FARE_HEADERS, start=1)}
_FL = {h: get_column_letter(i) for h, i in _FARE_COL.items()}   # formulas name columns by header

ANALYSIS_HEADERS = [
    "Driver Name", "Date", "Time", "Booking Code", "Week", "Pick-up Zone", "Drop-off Zone",
    "Pick-up District", "Drop-off District", "Pick-up Province", "Drop-off Province",
    "Surge", "Queue Type", "Stops",
    "Passenger Paid (THB)", "Passenger Total (THB)", "App Fee (THB)", "Other Adjustments (THB)", "Fare Refund (THB)",
    "Tip (THB)", "Check", "Approved By", "Group", "Admin", "Source File",
]
ANALYSIS_WIDTHS = [24, 11, 7, 16, 6, 12, 12, 14, 14, 9, 9, 6, 11, 6, 12, 12, 10, 12, 12, 8, 8, 11, 14, 12, 22]

# --- template styling (copied from the team's file) ---
_MED = Side(style="medium", color="000000")
_BORDER = Border(left=_MED, right=_MED, top=_MED, bottom=_MED)
_HEAD_FONT = Font(name="Calibri", bold=True, color="FFFFFFFF", size=9)
_HEAD_FILL = PatternFill("solid", fgColor="FF3C78D8")
_BODY_FONT = Font(name="Arial", size=10)
_THIN = Side(style="thin", color="BFBFBF")
_THIN_BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)


TIME_BANDS = ["00:01-05:59", "06:00-11:59", "12:00-17:59", "18:00-23:59", "N/A"]


def time_band(hhmm) -> str:
    """Team's Time column is a 6-hour band, not a clock time. Unknown (or disabled) -> 'N/A'."""
    if config.TIME_BAND_SOURCE != "screen_clock":
        return "N/A"
    t = _parse_time(hhmm)
    if t is None:
        return "N/A"
    return TIME_BANDS[t.hour // 6]


def _add_time_dropdown(ws):
    dv = DataValidation(type="list", formula1='"' + ",".join(TIME_BANDS) + '"', allow_blank=True)
    dv.error, dv.errorTitle = "เลือกช่วงเวลาจากรายการ", "Time"
    ws.add_data_validation(dv)
    dv.add("C2:C10000")


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


# When the photos carry no passenger figures at all, estimate P from the driver's base fare.
# Medians of รวมค่าโดยสาร / base measured on 1,030 real rows (2026-09-04); the older figures were
# ratios of ยอดที่ผู้โดยสารชำระ and ran ~20% high for cars.
FARE_RATIO = {"Saver Bike": 1.03, "Standard Bike": 1.17, "Standard Car": 1.25}
FARE_RATIO_DEFAULT = 1.16


def passenger_fare(t):
    """Column P per the team's convention (config.PASSENGER_FARE_SOURCE); falls back to the
    other line, derived if need be, then to a per-service-type estimate off the base fare."""
    paid, total = t.get("passenger_paid"), t.get("passenger_total")
    if config.PASSENGER_FARE_SOURCE == "paid":
        if paid is None and total is not None:
            paid = total - (t.get("app_fee") or 0) - (t.get("other_adj") or 0)
        val = paid
    else:
        if total is None and paid is not None:
            total = paid + (t.get("app_fee") or 0) + (t.get("other_adj") or 0)
        val = total
    if val is None and t.get("base_fare"):
        val = round(t["base_fare"] * FARE_RATIO.get(t.get("service_type") or "", FARE_RATIO_DEFAULT))
    return val


def passenger_fare_estimated(t) -> bool:
    """True when passenger_fare() had to estimate (no passenger figures in the photos)."""
    return (t.get("passenger_paid") is None and t.get("passenger_total") is None
            and bool(t.get("base_fare")))


def place(address, district, province_code) -> str:
    """What Sheet1 shows for pick-up and drop-off.

    It used to be the zone, and 10,942 of 13,077 rows came out "Downtown" — the fallback for any
    Bangkok district the zone table does not name, which made the column say almost nothing. Ops
    asked on 2026-09-05 for the place printed on the slip instead. The zone is still the answer
    when there is no address: rows read between 2026-09-02 and 2026-09-05 have none, because the
    field was switched off to save output tokens, and a blank cell would be worse than a coarse
    one. Analysis keeps the zone columns, so nothing is lost by this."""
    return (address or "").strip() or zone_for(district, province_code, None)


def _write_main_row(ws, row, driver_name, t, locations=False):
    """One trip in the team's column order. `locations` swaps the zone in F/G for the place the
    slip actually names — the Phase 2 file is this same sheet with those two cells filled in,
    which is what Ops asked for: everything they already read, plus the real address."""
    d = datetime.strptime(t["trip_date"], "%Y-%m-%d")
    pf = passenger_fare(t)
    values = [
        driver_name,                                            # A
        d,                                                      # B Date & Time
        time_band(t.get("trip_time")),                          # C  6-hour band (team format)
        t.get("service_type"),                                  # D
        t.get("payment_method"),                                # E
        (place(t.get("pickup_text"), t.get("pickup_district"), t.get("pickup_code")) if locations
         else zone_for(t.get("pickup_district"), t.get("pickup_code"), t.get("pickup_text"))),   # F
        (place(t.get("dropoff_text"), t.get("dropoff_district"), t.get("dropoff_code")) if locations
         else zone_for(t.get("dropoff_district"), t.get("dropoff_code"), t.get("dropoff_text"))),  # G
        t.get("distance_km"),                                   # H
        t.get("duration_mins"),                                 # I
        f"=K{row}+M{row}+N{row}",                               # J net (template formula)
        t.get("base_fare"),                                     # K
        t.get("intl_fee") or 0,                                 # L
        t.get("bonus") or 0,                                    # M
        t.get("turbo") or 0,                                    # N
        t.get("tolls") or 0,                                    # O
        pf,                                                     # P passenger fare (team convention)
        # What Grab kept out of the fare: the passenger's money minus the fare the rider was paid
        # for the ride. It used to subtract NET, which also contains the bonus and the turbo —
        # money Grab ADDS on top of the fare, not something it takes out of it. With incentives
        # the column read low, and on a ฿35 ride with a ฿20 bonus and a ฿41 fare it read -14
        # (Norm Asia, 2026-09-17; 1,017 of W37's rows carry an incentive).
        f"=P{row}-K{row}" if pf is not None else None,          # Q
        t.get("customer_image"),                                # R traceback to the delivered image
    ]
    for col, v in enumerate(values, start=1):
        cell = ws.cell(row=row, column=col)
        cell.value = v  # explicit assign — ws.cell(value=None) would NOT clear a cell
        cell.font = _BODY_FONT
        cell.border = _BORDER
        if col == 2:
            cell.number_format = "d-mmm-yy"
        elif col == 3:
            cell.alignment = Alignment(horizontal="center")
        elif locations and col in (6, 7):
            cell.alignment = Alignment(vertical="top", wrap_text=True)
    if pf is not None and passenger_fare_estimated(t):
        # estimated P (and its Q) render italic grey so readers can tell them from read values
        est_font = Font(name=_BODY_FONT.name, size=_BODY_FONT.size, italic=True, color="7F7F7F")
        ws.cell(row=row, column=16).font = est_font
        ws.cell(row=row, column=17).font = est_font


def iso_week(trip_date: str) -> str:
    """'2026-09-07' -> '2026-W36'. Zero-padded so plain string comparison orders weeks."""
    y, w, _ = datetime.strptime(trip_date, "%Y-%m-%d").isocalendar()
    return f"{y}-W{w:02d}"


def in_location_scope(trip_date: str) -> bool:
    """From W36 on a trip is no longer in the first file. It is in Phase 2 or Phase 3."""
    return bool(trip_date) and iso_week(trip_date) >= LOCATION_FROM_WEEK


def in_fare_lines_scope(trip_date: str) -> bool:
    return bool(trip_date) and iso_week(trip_date) >= FARE_LINES_FROM_WEEK


def _n(v):
    return v if v is not None else 0


def _write_fare_row(ws, row, driver_name, t):
    """One trip in the Phase 3 layout (FARE_HEADERS). Signs as the slip prints them."""
    d = datetime.strptime(t["trip_date"], "%Y-%m-%d")
    ride = passenger_fare(t)
    # Only the part of the tip the net actually contains moves out of Bonus. The row's bonus has
    # carried the tip since the first reader (pipeline.apply_extraction), except where the slip's
    # own 'คุณได้รับ' left it out — #30298 prints tip 20 in the extra income and ฿78 = base 74 +
    # turbo 4 as what the rider got. Net follows 'คุณได้รับ' and must not move, so there the tip
    # stays out of the rider's columns (and that row's passenger block shows the 20 it lacks).
    tip = min(_n(t.get("tip")), max(_n(t.get("bonus")), 0))
    values = {
        "Driver Name": driver_name,
        "Date & Time": d,
        "Time": time_band(t.get("trip_time")),
        "Service Type": t.get("service_type"),
        "Payment Method": t.get("payment_method"),
        "Pick-up Location": place(t.get("pickup_text"), t.get("pickup_district"), t.get("pickup_code")),
        "Drop-off Location": place(t.get("dropoff_text"), t.get("dropoff_district"), t.get("dropoff_code")),
        "Distance (km)": t.get("distance_km"),
        "Duration (mins)": t.get("duration_mins"),
        # the tip left Bonus for a column of its own, so the net adds it back: same total as before
        "Net Earnings (THB)": "=" + "+".join(f"{_FL[h]}{row}" for h in (
            "Base Fare (THB)", "Bonus", "Turbo Incentive (THB)", "Tip (THB)")),
        "Base Fare (THB)": t.get("base_fare"),
        # stored as an absolute number since the first reader; the slip prints it negative
        "International Fee": -abs(t["intl_fee"]) if t.get("intl_fee") else 0,
        # the row's bonus has always carried the tip (pipeline.apply_extraction) — take it out
        "Bonus": _n(t.get("bonus")) - tip,
        "Turbo Incentive (THB)": _n(t.get("turbo")),
        "Reimbursements / Tolls (THB)": _n(t.get("tolls")),
        "Tip (THB)": tip,
        "Application Fee": _n(t.get("app_fee")),
        "Discount": _n(t.get("discount")),
        "Travel Insurance Fee": _n(t.get("insurance_fee")),
        "Passenger Tolls": _n(t.get("passenger_tolls")),
        # ค่าบริจาคเพื่อชดเชยคาร์บอน, and a line Grab itself labels "อื่นๆ" (W38: 72 rows, 1.9%)
        "Other Fees": _n(t.get("other_adj")),
        # the old app screen has no paid line: left empty rather than worked out from the rest
        "Passenger Fare (THB)": t.get("passenger_paid"),
        "Ride Fare (THB)": ride,
        "Grab Service Fee (THB)": (f"={_FL['Ride Fare (THB)']}{row}-{_FL['Base Fare (THB)']}{row}"
                                   if ride is not None else None),
        "Image": t.get("customer_image"),
    }
    for h, v in values.items():
        cell = ws.cell(row=row, column=_FARE_COL[h])
        cell.value = v
        cell.font = _BODY_FONT
        cell.border = _BORDER
        if h == "Date & Time":
            cell.number_format = "d-mmm-yy"
        elif h == "Time":
            cell.alignment = Alignment(horizontal="center")
        elif h in ("Pick-up Location", "Drop-off Location"):
            cell.alignment = Alignment(vertical="top", wrap_text=True)
    if ride is not None and passenger_fare_estimated(t):
        est_font = Font(name=_BODY_FONT.name, size=_BODY_FONT.size, italic=True, color="7F7F7F")
        ws.cell(row=row, column=_FARE_COL["Ride Fare (THB)"]).font = est_font
        ws.cell(row=row, column=_FARE_COL["Grab Service Fee (THB)"]).font = est_font


def _write_analysis_row(ws, row, driver_name, t):
    d = datetime.strptime(t["trip_date"], "%Y-%m-%d")
    values = [
        driver_name, d, _parse_time(t.get("trip_time")), t.get("booking_code"),
        f"=ISOWEEKNUM(B{row})",
        zone_for(t.get("pickup_district"), t.get("pickup_code"), t.get("pickup_text")),
        zone_for(t.get("dropoff_district"), t.get("dropoff_code"), t.get("dropoff_text")),
        t.get("pickup_district"), t.get("dropoff_district"),
        t.get("pickup_code"), t.get("dropoff_code"),
        "Y" if t.get("surge") else None, t.get("queue_type"), t.get("num_stops"),
        t.get("passenger_paid"), t.get("passenger_total"),
        t.get("app_fee"), t.get("other_adj"), t.get("fare_refund"),
        t.get("tip") or 0,
        t.get("check_status"),
        "auto" if t.get("auto_approved") else ("person" if t.get("committed") else "pending"),
        t.get("category"), t.get("admin"),
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


def _write_zone_map(wb):
    """Reference sheet: the district→zone rule this file was generated with (audit support)."""
    from zones import ZONES, PROVINCE_ZONE
    ws = wb.create_sheet("Zone Map")
    _style_header(ws, ["โซน", "เขต/อำเภอ (กทม.และปริมณฑล)", "จังหวัดทั้งจังหวัด (fallback)"], [14, 90, 30], medium=False)
    prov_th = {"BKK": "กรุงเทพฯ (ที่เหลือ)", "NBI": "นนทบุรี", "PTE": "ปทุมธานี", "SPK": "สมุทรปราการ",
               "SKN": "สมุทรสาคร", "NPT": "นครปฐม", "AYA": "อยุธยา", "CBI": "ชลบุรี"}
    rows = [(name, ", ".join(sorted(members)),
             ", ".join(prov_th[c] for c, z in PROVINCE_ZONE.items() if z == name)) for name, members in ZONES]
    rows.append(("Downtown", "เขตอื่นทั้งหมดในกรุงเทพฯ ที่ไม่อยู่ในโซนข้างบน", prov_th["BKK"]))
    for i, r in enumerate(rows, start=2):
        for c, v in enumerate(r, start=1):
            cell = ws.cell(row=i, column=c, value=v)
            cell.font, cell.border = _BODY_FONT, _THIN_BORDER
            cell.alignment = Alignment(vertical="top", wrap_text=(c == 2))
    ws.cell(row=len(rows) + 3, column=1,
            value="ลำดับการตัดสิน: เขต/อำเภอ → คำในที่อยู่ → จังหวัด → Downtown · ที่มาของแต่ละแถวดูในชีท Analysis (District/Province/Address) · นิยามรอทีมยืนยันจากไฟล์ Zone Mapping").font = Font(name="Arial", size=9, color="666666")


def _new_workbook():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = SHEET
    _style_header(ws, HEADERS, COL_WIDTHS, medium=True)
    _add_time_dropdown(ws)
    wa = wb.create_sheet(ANALYSIS_SHEET)
    _style_header(wa, ANALYSIS_HEADERS, ANALYSIS_WIDTHS, medium=False)
    wa.freeze_panes = "A2"
    _write_zone_map(wb)
    return wb


# ---------- export (cloud + local) ----------

def build_workbook(rows: list[dict]) -> bytes:
    """Rows from db.query_trips (each carries driver_name). Returns xlsx bytes.

    Stops at the week Phase 2 begins. From LOCATION_FROM_WEEK on, a trip belongs to the Phase 2
    file and to nothing else — this workbook is finished, and each round rebuilding it with the
    new weeks folded in was exactly the 'still writing the old file' Ops asked us to stop."""
    rows = [t for t in rows if not in_location_scope(t.get("trip_date"))]
    wb = _new_workbook()
    ws, wa = wb[SHEET], wb[ANALYSIS_SHEET]
    for i, t in enumerate(rows, start=2):
        _write_main_row(ws, i, t["driver_name"], t)
        _write_analysis_row(wa, i, t["driver_name"], t)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_location_workbook(rows: list[dict]) -> bytes | None:
    """The Phase 2 file: the delivered sheet, with the place the slip names in Pick-up/Drop-off.

    Same columns as the customer's Rider Trips.xlsx, so it reads the same and can be handed over
    the same way — only F and G differ, carrying the address instead of the zone. A separate
    workbook on purpose: the customer's own file keeps the zone it has always had. Returns None
    when no trip is in scope yet, so a file of nothing but headers never lands on Drive."""
    wanted = [t for t in rows if in_location_scope(t.get("trip_date"))
              and not in_fare_lines_scope(t.get("trip_date"))]
    if not wanted:
        return None
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = LOCATION_SHEET
    widths = list(COL_WIDTHS) + [14, 14]
    widths[5] = widths[6] = 46                     # an address, not a one-word zone
    _style_header(ws, LOCATION_HEADERS, widths, medium=True)
    ws.freeze_panes = "A2"
    for i, t in enumerate(sorted(wanted, key=lambda x: (x.get("trip_date") or "", x["driver_name"])),
                          start=2):
        _write_main_row(ws, i, t["driver_name"], t, locations=True)
        for col, z in enumerate((zone_for(t.get("pickup_district"), t.get("pickup_code"), t.get("pickup_text")),
                                 zone_for(t.get("dropoff_district"), t.get("dropoff_code"), t.get("dropoff_text"))),
                                start=len(HEADERS) + 1):
            cell = ws.cell(row=i, column=col, value=z)
            cell.font, cell.border = _BODY_FONT, _BORDER
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_fare_lines_workbook(rows: list[dict]) -> bytes | None:
    """The Phase 3 file: from FARE_LINES_FROM_WEEK on, every line of the passenger's fare block.
    Same sheet name, place columns and trailing zones as Phase 2, so whatever reads Phase 2 finds
    its way around this one. None when no trip is in scope yet."""
    wanted = [t for t in rows if in_fare_lines_scope(t.get("trip_date"))]
    if not wanted:
        return None
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = LOCATION_SHEET
    _style_header(ws, FARE_LINES_HEADERS, FARE_WIDTHS + [14, 14], medium=True)
    ws.freeze_panes = "A2"
    zone_col = len(FARE_HEADERS) + 1
    for i, t in enumerate(sorted(wanted, key=lambda x: (x.get("trip_date") or "", x["driver_name"])),
                          start=2):
        _write_fare_row(ws, i, t["driver_name"], t)
        for col, z in enumerate((zone_for(t.get("pickup_district"), t.get("pickup_code"), t.get("pickup_text")),
                                 zone_for(t.get("dropoff_district"), t.get("dropoff_code"), t.get("dropoff_text"))),
                                start=zone_col):
            cell = ws.cell(row=i, column=col, value=z)
            cell.font, cell.border = _BODY_FONT, _BORDER
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def later_workbooks(rows: list[dict]) -> list[tuple[str, bytes]]:
    """(file name, bytes) for every workbook after the first that has rows in it — Phase 2, then
    Phase 3. The places that write the customer files all ask here, so a new phase is one change,
    not three."""
    out = []
    for name, build in ((LOCATION_FILE, build_location_workbook),
                        (FARE_LINES_FILE, build_fare_lines_workbook)):
        data = build(rows)
        if data:
            out.append((name, data))
    return out


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
    if not ws.data_validations.dataValidation:
        _add_time_dropdown(ws)
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
