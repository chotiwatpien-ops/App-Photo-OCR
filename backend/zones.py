# -*- coding: utf-8 -*-
"""District → zone mapping for the team's Excel template (Pick-up / Drop-off Location).

Zones used by the team: Downtown · North-DMK · East-SVB · West-Nont · South-Rama2
(DMK = Don Mueang, SVB = Suvarnabhumi, Nont = Nonthaburi, Rama2 = Rama II road corridor).

This is a BUSINESS definition, not a fact from the screenshot — edit the sets below to
match how the team draws the lines. Anything in Bangkok not listed is Downtown.
"""
import re

NORTH_DMK = {
    # Bangkok north
    "ดอนเมือง", "หลักสี่", "สายไหม",
    # Pathum Thani
    "เมืองปทุมธานี", "ปทุมธานี", "รังสิต", "คลองหลวง", "ธัญบุรี", "ลำลูกกา", "ลาดหลุมแก้ว",
    "สามโคก", "หนองเสือ",
}
EAST_SVB = {
    # Bangkok east
    "ลาดกระบัง", "มีนบุรี", "หนองจอก", "คลองสามวา",
    # Samut Prakan
    "บางพลี", "บางเสาธง", "เมืองสมุทรปราการ", "สมุทรปราการ", "บางบ่อ",
}
WEST_NONT = {
    # Nonthaburi
    "เมืองนนทบุรี", "นนทบุรี", "ปากเกร็ด", "บางบัวทอง", "บางใหญ่", "บางกรวย", "ไทรน้อย",
    # Bangkok west (Thonburi side, outer)
    "ตลิ่งชัน", "ทวีวัฒนา", "บางแค", "หนองแขม",
    # Nakhon Pathom
    "พุทธมณฑล", "สามพราน", "นครชัยศรี", "เมืองนครปฐม", "นครปฐม",
}
SOUTH_RAMA2 = {
    # Bangkok south-west along Rama II
    "บางขุนเทียน", "บางบอน", "จอมทอง", "ทุ่งครุ", "ราษฎร์บูรณะ",
    # Samut Sakhon + Samut Prakan west bank
    "เมืองสมุทรสาคร", "สมุทรสาคร", "กระทุ่มแบน", "บ้านแพ้ว", "พระประแดง", "พระสมุทรเจดีย์",
}
ZONES = [("North-DMK", NORTH_DMK), ("East-SVB", EAST_SVB), ("West-Nont", WEST_NONT), ("South-Rama2", SOUTH_RAMA2)]

# fallback when only the province is known
PROVINCE_ZONE = {"BKK": "Downtown", "NBI": "West-Nont", "PTE": "North-DMK", "SPK": "East-SVB",
                 "SKN": "South-Rama2", "NPT": "West-Nont", "AYA": "North-DMK", "CBI": "East-SVB"}

_STRIP = re.compile(r"^(เขต|อำเภอ|อ\.|แขวง|ตำบล|ต\.)\s*")


def _norm(s):
    return _STRIP.sub("", (s or "").strip())


def zone_for(district=None, province_code=None, address=None, on_date=None) -> str:
    """Best zone for a location. Trips dated from config.ZONE_TABLE_FROM on use the customer's
    zone table (zone_table.csv); earlier ones keep the zones they were delivered with.
    Old zones' order: district table → keywords in the address → province → Downtown."""
    import config
    start = getattr(config, "ZONE_TABLE_FROM", None)
    if start and on_date and str(on_date) >= start:
        return table_zone(district, province_code, address)
    d = _norm(district)
    if d:
        for name, members in ZONES:
            if d in members:
                return name
        if province_code == "BKK" or not province_code:
            return "Downtown"
    if address:
        for name, members in ZONES:
            if any(m in address for m in members):
                return name
    if province_code in PROVINCE_ZONE:
        return PROVINCE_ZONE[province_code]
    return "Downtown" if (d or address) else ""


# ---- the customer's zone table (requirement 2026-11-08) ------------------------------------
# zone_table.csv: one row per area, `level` แขวง | เขต | อำเภอ | เมือง. A sub-district (แขวง) the
# customer named overrides its district: Lumphini is named apart from Pathum Wan. Slips carry no
# coordinates, so a "polygon" is decided by the names in the address, never by a map line.
TABLE_PATH = __import__("pathlib").Path(__file__).with_name("zone_table.csv")
TABLE_OTHER = "Blue"           # the customer's "Other": anywhere the other zones do not name
_table = None


def _subdistricts():
    """{แขวง: เขต} for Bangkok. The reader sometimes gives the sub-district where the district
    belongs (เสนานิคม for จตุจักร), which left the trip in Other. Only the district field is
    translated, never words in the address, and a name two districts share (บางจาก, บางมด) is
    left out of the file."""
    import csv
    path = __import__("pathlib").Path(__file__).with_name("bkk_subdistricts.csv")
    with open(path, encoding="utf-8") as fh:
        return {r["khwaeng"].strip(): r["khet"].strip() for r in csv.DictReader(fh)}


SUBDISTRICT_OF = _subdistricts()


def load_table(path=None):
    """(sub-districts, districts): [(name, zone)] longest name first, so 'คลองตันเหนือ' wins
    over 'คลองตัน' when an address is searched."""
    import csv
    subs, dists = [], []
    with open(path or TABLE_PATH, encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            name, zone = (r.get("name") or "").strip(), (r.get("zone") or "").strip()
            if not name or not zone:
                continue
            (subs if r.get("level") == "แขวง" else dists).append((name, zone))
    by_len = lambda kv: -len(kv[0])                                     # noqa: E731
    return sorted(subs, key=by_len), sorted(dists, key=by_len)


def table_zone(district=None, province_code=None, address=None, table=None) -> str:
    """Zone by the customer's table. Order: a named sub-district in the address → the district
    the reader gave → a named district in the address → Other (blue). Blue covers places outside
    Bangkok the table does not name too (Fiat, 2026-11-08), so no trip is left without a zone;
    a trip with no location at all stays blank."""
    global _table
    if table is None:
        _table = _table or load_table()
        table = _table
    subs, dists = table
    d, addr = _norm(district), address or ""
    d = SUBDISTRICT_OF.get(d, d)
    for name, zone in subs:
        if name in addr or d == name:
            return zone
    for name, zone in dists:
        if d == name:
            return zone
    for name, zone in dists:
        if name in addr:
            return zone
    return TABLE_OTHER if (d or addr or province_code) else ""
