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


def zone_for(district=None, province_code=None, address=None) -> str:
    """Best zone for a location. Order: district table → keywords in the address → province → Downtown."""
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
