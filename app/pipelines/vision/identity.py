"""跨模态矛盾：来电号码与自称身份的冲突检测（T-10 / FR-2.4b）。

只看两样东西：号码本身（区号 / 号段）和文本里自称的身份。

- 固话区号指向的城市，与自称的"本地公安/法院/银行"对不上；
- 自称公检法却用虚拟运营商号段（170/171/162/165/167）；
- 自称官方却只留个人手机号（弱信号，权重很低）。

号码段表在 ``app/kb/phone_prefix.json``，不联网、不查运营商接口，
所以**这是启发式，输出「疑似」，不是深度伪造检测器**；
号码归属地本身也不能证明持机人身份。
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from app.schemas import Evidence, Modality, SourceKind

LOGGER = logging.getLogger(__name__)

PHONE_PATH = Path(__file__).resolve().parents[2] / "kb" / "phone_prefix.json"
MAX_CONFIDENCE = 0.90
NOTE = "启发式，疑似，不是深度伪造检测器"
# 号段冲突的权重：跨省/跨市最强，同省不同市次之，官方用虚拟号再次之
DIFFERENT_REGION_CONFIDENCE = 0.70
SAME_PROVINCE_CONFIDENCE = 0.45
VIRTUAL_AUTHORITY_CONFIDENCE = 0.60
AUTHORITY_MOBILE_CONFIDENCE = 0.15


def number_identity_mismatch(phone: str, claim: str) -> Evidence:
    """判断号码归属与自称身份是否存在矛盾。

    返回 ``Evidence(kind=SourceKind.CROSS_MODAL)``；号码不可解析或没有冲突时
    confidence=0.0。函数不联网、不抛异常。
    """
    data = _load_rules()
    note = str(data.get("note", NOTE))
    digits = _digits(phone)
    claim_text = (claim or "").strip()
    meta: dict = {
        "phone_masked": _mask(phone),
        "claim": claim_text[:120],
        "note": note,
        "signals": [],
    }
    if len(digits) < 7:
        meta["reason"] = "号码位数不足，无法判断"
        return _evidence(0.0, "号码不足 7 位，无法判断归属", meta)

    area = _lookup_area(digits, data)
    head = digits[:3]
    mobile = data.get("mobile_heads", {}).get(head)
    is_virtual = head in set(data.get("virtual_operator_heads") or [])
    authority = any(keyword in claim_text for keyword in data.get("authority_keywords") or [])
    claimed_places = _claimed_places(claim_text, data)

    confidence = 0.0
    signals: list[str] = []
    if area is not None:
        code, info = area
        city = str(info.get("city", ""))
        province = str(info.get("province", ""))
        meta["area"] = {"code": code, "city": city, "province": province}
        if claimed_places:
            claimed_provinces = _provinces_of(claimed_places, data)
            meta["claimed_places"] = sorted(claimed_places)
            if city in claimed_places:
                meta["reason"] = "号码归属地与自称一致"
            elif province in claimed_provinces or province in claimed_places:
                confidence = max(confidence, SAME_PROVINCE_CONFIDENCE)
                signals.append("same_province_diff_city")
            else:
                confidence = max(confidence, DIFFERENT_REGION_CONFIDENCE)
                signals.append("different_region")
    elif mobile is not None:
        meta["operator"] = str(mobile.get("operator", ""))
    if is_virtual:
        meta["virtual_operator"] = True
    if is_virtual and authority:
        confidence = max(confidence, VIRTUAL_AUTHORITY_CONFIDENCE)
        signals.append("virtual_operator_authority")
    elif authority and area is None:
        # 官方号码通常是固话/短号；个人手机号只是弱信号，避免误伤真实来电
        confidence = max(confidence, AUTHORITY_MOBILE_CONFIDENCE)
        signals.append("authority_mobile_weak")

    confidence = min(MAX_CONFIDENCE, confidence)
    meta["signals"] = signals
    region_text = _region_text(meta)
    if confidence <= 0:
        text = f"号码 {meta['phone_masked']} 与自称身份未见明显冲突"
    else:
        text = f"号码 {meta['phone_masked']}（{region_text}）与自称「{claim_text[:40]}」疑似不符"
    return _evidence(confidence, text, meta)


def _load_rules() -> dict:
    try:
        return json.loads(PHONE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        LOGGER.warning("号码段表加载失败，按空表处理：%s", exc)
        return {}


def _digits(phone: str) -> str:
    digits = re.sub(r"\D", "", phone or "")
    if digits.startswith("0086"):
        digits = digits[4:]
    elif digits.startswith("86") and len(digits) > 11:
        digits = digits[2:]
    return digits


def _mask(phone: str) -> str:
    raw = (phone or "").strip()
    if "*" in raw:
        return raw
    digits = _digits(raw)
    if len(digits) >= 7:
        return f"{digits[:3]}****{digits[-4:]}"
    return f"{digits[:2]}****" if digits else "****"


def _lookup_area(digits: str, data: dict) -> tuple[str, dict] | None:
    area_codes = data.get("area_codes") or {}
    if not digits.startswith("0"):
        return None
    for length in (4, 3):
        code = digits[:length]
        info = area_codes.get(code)
        if isinstance(info, dict):
            return code, info
    return None


def _claimed_places(claim: str, data: dict) -> set[str]:
    places: set[str] = set()
    claim_places = data.get("claim_places") or {}
    for city, aliases in claim_places.items():
        for alias in aliases or []:
            if alias and alias in claim:
                places.add(str(city))
                break
    return places


def _provinces_of(places: set[str], data: dict) -> set[str]:
    province_by_city: dict[str, str] = {}
    for info in (data.get("area_codes") or {}).values():
        if isinstance(info, dict) and info.get("city") and info.get("province"):
            province_by_city[str(info["city"])] = str(info["province"])
    return {province_by_city.get(place, place) for place in places}


def _region_text(meta: dict) -> str:
    area = meta.get("area")
    if area:
        return f"{area['province']}{area['city']} {area['code']}"
    if meta.get("virtual_operator"):
        return "虚拟运营商号段"
    if meta.get("operator"):
        return str(meta["operator"])
    return "归属未知"


def _evidence(confidence: float, text: str, meta: dict) -> Evidence:
    confidence = max(0.0, min(1.0, float(confidence)))
    return Evidence(
        code="number_identity_mismatch",
        label="号码与自称身份疑似不符",
        category="entity",
        text=text,
        weight=confidence,
        confidence=confidence,
        modality=Modality.TEXT,
        kind=SourceKind.CROSS_MODAL,
        meta=meta,
    )
