#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""信息网络传播权纠纷 · 一审管辖判定引擎

确定性查表计算，不做任何推理。调用方（AI）负责从案件材料中抽取参数、
解释输出结果并起草文书；本脚本只负责保证「同样的输入永远得到同样的、
可追溯到法条和数据源的结论」。

用法：
    python jurisdiction.py --def-prov 浙江省 --def-city 杭州市 --def-district 西湖区 --amount 800000
    python jurisdiction.py --def-prov 天津市 --def-city 天津市 --def-district 西青区 --def-zone 华苑科技园 --filing-date 2026-08-06 --amount 800000
    python jurisdiction.py --help
    python jurisdiction.py --selftest

输出：JSON（默认）或 --text 人类可读格式。
"""

import argparse
import json
import os
import re
import sys
from datetime import date

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")

# 该省级别管辖标准未收录时的通用推定阈值（元）
GENERIC_BASIC = 1_000_000
# 不是级别管辖门槛。低于 1 万元时，调用方经常把「100万」传成 100。
# 法定赔偿可以低于 1 万元，因此只降置信度，不拒绝计算。
SMALL_AMOUNT_YUAN = 10_000
# 不是全国高院一审门槛。未收录 high_court_min 的省份，标的额达到这一金额时
# 不得再以中等置信度锁定中院；低于这一金额的中院结论保持原置信度。
HIGH_COURT_DATA_GAP_YUAN = 5_000_000_000


def _load(name):
    with open(os.path.join(DATA, name), encoding="utf-8") as f:
        return json.load(f)


COURTS = _load("courts.json")
DIVISIONS = _load("divisions.json")
PROVINCES = _load("provinces.json")
SPECIAL = _load("special_courts.json")
LOCAL_OVERRIDES = _load("local_venue_overrides.json")

BASIS_VENUE = "《最高人民法院关于审理侵害信息网络传播权民事纠纷案件适用法律若干问题的规定》（法释〔2020〕19号）第15条"


# ---------- 名称归一化 ----------

def norm_city(s):
    return re.sub(r"市$", "", (s or "").strip()).strip()


def norm_area(s):
    return re.sub(
        r"(经济技术开发区|高新技术产业开发区|经济开发区|开发区|新区|街道办事处|街道|镇|区|县|市|盟|地区)$",
        "", (s or "").strip()).strip()


def area_hit(a, q):
    """法院辖区名 a 是否命中查询地名 q。宽松匹配，容忍行政区划后缀差异。"""
    if not q:
        return False
    na, nq = norm_area(a), norm_area(q)
    if a == q or a.find(q) >= 0 or q.find(a) >= 0:
        return True
    if na and nq:
        if na == nq:
            return True
        if len(na) > 1 and nq.find(na) >= 0:
            return True
        if len(nq) > 1 and na.find(nq) >= 0:
            return True
    return False


def norm_zone(s):
    """特殊园区/功能区名称归一化，但坚持精确匹配，避免把「华苑」误当成华苑科技园。"""
    return re.sub(r"[\s（）()·]", "", (s or "").strip()).lower()


def resolve_zone(province, zone, no_special_zone=False):
    """返回 (state, override)。state: unknown / regular / special / unrecognized。"""
    if no_special_zone:
        return "regular", None
    if not (zone or "").strip():
        return "unknown", None
    nz = norm_zone(zone)
    for item in LOCAL_OVERRIDES.get("zones", []):
        if item.get("province") != province:
            continue
        names = [item.get("name", "")] + item.get("aliases", [])
        if any(nz == norm_zone(x) for x in names if x):
            return "special", item
    return "unrecognized", None


def potential_zone_overrides(province, district):
    """区级地址可能横跨特别管辖区域时，列出需进一步核验的规则。"""
    if not district:
        return []
    nd = norm_area(district)
    nz = norm_zone(district)
    return [
        item for item in LOCAL_OVERRIDES.get("zones", [])
        if item.get("province") == province
        and (
            # 这里只判断“可能涉及”，不会据此确认园区内；因此宁可把含有
            # 南开/西青区名的复合地址降级待核，也不能被 area_hit 的宽松
            # 基础法院匹配抢先写死。
            any(area_hit(x, district) for x in item.get("affected_districts", []))
            or any(norm_zone(alias) in nz for alias in item.get("aliases", []) if norm_zone(alias))
        )
    ]


def local_rule_active(item, filing_date):
    """局部规则是否适用于该案。filing_date 已由 analyze 校验为 ISO 日期。"""
    if not filing_date:
        return True  # 默认任务是判断当前准备新立的案件
    return date.fromisoformat(filing_date) >= date.fromisoformat(item["effective_date"])


def multiple_intermediate(province):
    """一省有多家中院、不能拼出一个法院名时，返回数据里的占位说明。"""
    info = (PROVINCES.get(province) or {}).get("intermediate_court") or {}
    if info.get("status") == "multiple" and info.get("label") and info.get("warning"):
        return info
    return None


def inter_name(x):
    """由地级市名推导中院名称。

    自治州、盟、地区的中院名不含「市」（延边朝鲜族自治州中级人民法院）；
    普通地级市则含「市」。注意不能按单字「州」判断——苏州、温州、常州、
    台州、湖州、广州、郑州、福州等均为普通地级市。
    """
    b = re.sub(r"市$", "", (x or "").strip())
    if re.search(r"自治州$|盟$|地区$", b):
        return b + "中级人民法院"
    return b + "市中级人民法院"


def norm_province(s):
    """省级行政区名归一化。接受「浙江」「内蒙古」这类口语简称，无法识别时返回 None。

    省级行政区是固定的 31 个，可以严格校验；错误的省名必须拒绝，
    不能像市县那样降级处理——否则会凭空编出「某某市有知产管辖权的基层人民法院」。
    """
    s = (s or "").strip()
    if not s:
        return None
    if s in PROVINCES:
        return s
    for suf in ("省", "市"):
        if s + suf in PROVINCES:
            return s + suf
    for p in PROVINCES:                      # 内蒙古/广西/西藏/宁夏/新疆等自治区简称
        if p.startswith(s) and ("自治区" in p or "特别行政区" in p):
            return p
    return None


def place_known(province, city, district):
    """城市/区县名是否出现在本省行政区划表中。

    用于区分「地名写错了」与「地名对但辖区表未收录」。直辖市在映射表中
    没有条目，一律视为已知，避免误判。
    """
    m = DIVISIONS.get(province)
    if not m:
        return True
    parents = set(m.values())
    for q in (city, district):
        if not q:
            continue
        if q in m or q in parents:
            return True
        nq = norm_area(q)
        if any(norm_area(k) == nq for k in m):
            return True
        if any(norm_city(p) == norm_city(q) for p in parents):
            return True
    return False


def lookup_div(province, name):
    """县级市/县/区 → 所属地级市。如 开原市 → 铁岭市。"""
    m = DIVISIONS.get(province)
    if not m or not name:
        return None
    n = name.strip()
    if n in m:
        return m[n]
    for suf in ("市", "县", "区", "旗"):
        if n + suf in m:
            return m[n + suf]
    nn = norm_area(n)
    if nn and nn != n:
        for k in m:
            if norm_area(k) == nn:
                return m[k]
    return None


# ---------- 级别管辖 ----------

def get_cap(province, city):
    """返回 (cap_info, status)。cap_info 为 None 表示该省未收录。"""
    e = PROVINCES.get(province)
    if not e:
        return None, "missing"
    cap, status = e.get("cap"), e.get("cap_status", "unknown")
    if cap == "noCap":
        return {"no_cap": True}, status
    if isinstance(cap, dict) and "cities9" in cap:
        c = norm_city(city)
        in9 = any(norm_city(m) == c for m in cap["cities9"])
        return {"max": cap["cap9"] if in9 else cap["capOther"], "tier": "重点城市" if in9 else "其他城市"}, status
    if isinstance(cap, (int, float)):
        return {"max": cap}, status
    return None, "missing"


def fmt_wan(y):
    w = y / 10000.0
    if w == int(w):
        return "%d万元" % int(w)
    # 1 元 = 0.0001 万元。不能只留两位小数，否则 4,999,999 元会显示成
    # 「500.00万元＜500万元」，掩盖决定级别管辖的 1 元差异。
    return (("%.6f" % w).rstrip("0").rstrip(".")) + "万元"


def _apply_small_amount(result, amount):
    """不足 1 万元时降置信度。调用方把万元数字直接传入时，会静默判成基层。"""
    if not (isinstance(amount, (int, float)) and 0 < amount < SMALL_AMOUNT_YUAN):
        return result
    shown = int(amount) if amount == int(amount) else amount
    corrected = shown * 10000
    corrected_txt = str(int(corrected)) if corrected == int(corrected) else str(corrected)
    result = dict(result)
    result["warnings"] = list(result.get("warnings") or []) + [
        "标的额按 %s 元（%s）计算。若材料中的数字以万元为单位，请改传 %s。"
        "不足 1 万元时不维持中等置信度；法定赔偿可以低于 1 万元，确认单位后再使用结论。"
        % (shown, fmt_wan(amount), corrected_txt)
    ]
    result["confidence"] = "low"
    return result


def _downgrade_if_high_court_unknown(result, province, amount):
    """没有高院起点数据时，超大标的不得锁成中院。"""
    if result.get("level") != "中级":
        return result
    if isinstance((PROVINCES.get(province) or {}).get("high_court_min"), (int, float)):
        return result
    if not isinstance(amount, (int, float)) or amount < HIGH_COURT_DATA_GAP_YUAN:
        return result
    result = dict(result)
    result["level"] = "中级或高级"
    result["confidence"] = "low"
    result["reason"] = (
        "标的额 %s 已超过基层受理上限，但本省高级人民法院一审起点未收录，"
        "不能在中级人民法院与高级人民法院之间锁定" % fmt_wan(amount))
    result["warnings"] = list(result.get("warnings") or []) + [
        "本省高级人民法院一审起点未收录。50亿元不是全国统一门槛，只是缺少该数据时的降级线，"
        "达到该金额不得把某一家中级人民法院写成已经锁定的管辖法院。"
    ]
    return result


def decide_level(province, city, amount, is_foreign=False):
    """判定级别管辖。返回 dict: level / confidence / reason / warnings"""
    result = _decide_level(province, city, amount, is_foreign)
    result = _downgrade_if_high_court_unknown(result, province, amount)
    return _apply_small_amount(result, amount)


def _decide_level(province, city, amount, is_foreign=False):
    # 标的额是级别管辖的唯一决定因素。缺失时不得静默按 0 处理——那等于
    # 默认判成基层法院，会把本该由中院管辖的案件算错。
    # 门槛按法〔2025〕167号附件「不含本数」，故此处用严格小于。
    if amount is None or amount <= 0:
        return {
            "level": "基层",
            "confidence": "low",
            "reason": "未提供有效的诉讼请求标的额，级别管辖无法判定",
            "warnings": ["未提供标的额（或填了非正数），无法判断本案应由哪一级人民法院管辖。"
                         "下方法院仅为地域管辖的结果，补充标的额后必须重新判定。"],
        }

    province_info = PROVINCES.get(province) or {}
    high_min = province_info.get("high_court_min")
    if isinstance(high_min, (int, float)) and amount >= high_min:
        high_court = province_info.get("high_court") or (province + "高级人民法院")
        high_warnings = []
        if is_foreign:
            high_warnings.append("涉外/涉港澳台案件的级别管辖可能另有规定，须单独核实")
        return {
            "level": "高级", "confidence": "medium",
            "reason": "标的额 %s ≥ 高级人民法院一审标准 %s（含本数），由%s管辖"
                      % (fmt_wan(amount), fmt_wan(high_min), high_court),
            "warnings": high_warnings,
        }

    cap, status = get_cap(province, city)
    warnings = []

    if not cap:
        lv = "基层" if amount < GENERIC_BASIC else "中级"
        return {
            "level": lv,
            "confidence": "low",
            "reason": "该省级别管辖标准未收录；按通用推定阈值 %s 判断为%s法院管辖" % (fmt_wan(GENERIC_BASIC), lv),
            "warnings": ["级别管辖结论为通用推定，未经核实，立案前必须向法院或按省高院文件确认"],
        }

    if cap.get("no_cap"):
        return {
            "level": "基层",
            "confidence": "medium" if status == "sourced" else "low",
            "reason": "该市各基层法院均有知产管辖权、无标的额上限，由基层法院管辖",
            "warnings": warnings,
        }

    mx = cap["max"]
    tier = ("（%s档）" % cap["tier"]) if cap.get("tier") else ""
    fw = "（涉外/涉港澳台，另需核实特别规定）" if is_foreign else ""

    if status == "presumed":
        note = (PROVINCES.get(province) or {}).get("note") or "本省标的额标准系推定值，使用前须核实"
        warnings.append(note)
    confidence = "low" if status == "presumed" else "medium"

    if is_foreign:
        warnings.append("涉外/涉港澳台案件的级别管辖可能另有规定，须单独核实")

    if amount < mx:
        return {"level": "基层", "confidence": confidence,
                "reason": "标的额 %s ＜ 本地基层受理上限 %s%s%s，由基层法院管辖" % (fmt_wan(amount), fmt_wan(mx), tier, fw),
                "warnings": warnings}
    return {"level": "中级", "confidence": confidence,
            "reason": "标的额 %s ≥ 本地基层受理上限 %s%s%s，由中级法院管辖" % (fmt_wan(amount), fmt_wan(mx), tier, fw),
            "warnings": warnings}


# ---------- 地域定位 ----------

def locate_court(province, city, district, parent):
    """在该省法院辖区表中定位具体基层法院。"""
    rd = COURTS.get(province)
    if not rd or not rd.get("courts"):
        return {"none": True}
    cN = norm_city(parent or city)

    def scan(q):
        if not q:
            return []
        return [ct for ct in rd["courts"] if any(area_hit(a, q) for a in ct.get("a", []))]

    # 匹配层级决定结论可信度：命中区县/本市最可靠；只能靠所属地级市名兜底的，
    # 命中的往往是该市市区的法院，对下辖县级市的被告而言是错的，必须降级处理。
    hits, via, level = scan(district), district, "district"
    if not hits:
        hits, via, level = scan(city), city, "city"
    if not hits and parent and norm_city(parent) != norm_city(city):
        hits, via, level = scan(parent), parent, "parent-fallback"
    if len(hits) > 1:
        by_city = [ct for ct in hits if cN and ct["c"].find(cN) >= 0]
        if by_city:
            hits = by_city
    if len(hits) == 1:
        matched = next((a for a in hits[0].get("a", []) if area_hit(a, via)), "")
        return {"court": hits[0]["c"], "matched": matched, "match_level": level, "via": via}
    if len(hits) > 1:
        return {"multi": [ct["c"] for ct in hits]}
    return {"none": True}


def court_for_place(province, city, district, amount, is_foreign=False,
                    zone="", no_special_zone=False, filing_date="", zone_arg="--zone",
                    outside_arg="--no-special-zone"):
    """给定一个连接点所在地，算出该走哪个法院。

    zone 是经材料确认的特殊园区/功能区。特别管辖必须走这一独立维度，
    不能塞进区县辖区表，否则会把整个行政区误改，或被宽松地名匹配误命中。
    """
    parent = lookup_div(province, city) or (lookup_div(province, district) if district else None)
    std_city = parent or city
    lv = decide_level(province, std_city, amount, is_foreign)
    warnings = list(lv["warnings"])
    extra = ""
    if parent and norm_city(parent) != norm_city(city):
        extra = "“%s”属%s，" % (city, parent)

    zone_state, zone_override = resolve_zone(province, zone, no_special_zone)
    legacy_override = None
    if zone_state == "special" and not local_rule_active(zone_override, filing_date):
        legacy_override = zone_override
        zone_state, zone_override = "legacy", None

    if lv["level"] == "高级":
        province_info = PROVINCES.get(province) or {}
        court = province_info.get("high_court") or (province + "高级人民法院")
        note = "已达到高级人民法院一审标准"
        if zone_state == "special":
            note += "；华苑科技园公告仅调整符合基层、中级法院一审标准的案件，不改变高级人民法院级别管辖"
        return {"court": court, "level": "高级人民法院", "reason": lv["reason"],
                "confidence": lv["confidence"], "precise": True,
                "extra": extra + note, "warnings": warnings}

    if lv["level"] == "中级或高级":
        warnings.append(
            "信息网络传播权侵权民事案件不属知识产权法院管辖范围，不得改写到知识产权法院"
            "（计算机软件著作权案件除外）")
        return {"court": "%s有管辖权的中级人民法院或高级人民法院" % province,
                "level": "中级或高级人民法院", "reason": lv["reason"],
                "confidence": "low", "precise": False,
                "extra": extra + "级别未在中院与高院之间锁定", "warnings": warnings}

    if zone_state == "special":
        if lv["level"] == "中级":
            court = zone_override["intermediate_court"]
            level_name = "中级人民法院"
            warnings.append(
                "信息网络传播权侵权民事案件不属知识产权法院管辖范围，达到中院级别标准的应向普通中级人民法院起诉"
                "（计算机软件著作权案件除外）")
            appeal_note = ""
        else:
            court = zone_override["basic_court"]
            level_name = "基层人民法院"
            appeal_note = "；该院一审裁判的上诉法院为%s" % zone_override["basic_appeal_court"]
        warnings.append(
            "本结果按%s起的新立案规则计算；%s"
            % (zone_override["effective_date"], zone_override["transition"]))
        reason = "%s；依%s，由%s管辖" % (lv["reason"], zone_override["basis"], court)
        note = "已明确连接点位于%s，适用局部区域特别管辖%s" % (zone_override["name"], appeal_note)
        return {"court": court, "level": level_name, "reason": reason,
                "confidence": lv["confidence"], "precise": True,
                "extra": extra + note, "warnings": warnings,
                "special_rule": {
                    "id": zone_override["id"], "name": zone_override["name"],
                    "effective_date": zone_override["effective_date"],
                    "basis": zone_override["basis"], "source_url": zone_override["source_url"],
                    "appeal_court": zone_override.get("basic_appeal_court") if lv["level"] != "中级" else None,
                }}

    def finish(result):
        """给普通区划结果加上特殊园区的输入校验与歧义提示。"""
        if zone_state == "legacy":
            result["extra"] = (result.get("extra", "") +
                               "；本案正式立案日为%s，早于%s，继续适用原管辖分片"
                               % (filing_date, legacy_override["effective_date"])).strip("；")
            result["warnings"].append(legacy_override["transition"])
            return result

        if zone_state == "regular":
            result["extra"] = (result.get("extra", "") +
                               "；已明确该连接点不在已收录的特殊管辖园区内").strip("；")
            return result

        if zone_state == "unrecognized":
            result["warnings"].append(
                "未识别特殊区域“%s”，当前仅按普通行政区划给出方向性结果；请核对名称或更新特别管辖数据。"
                % zone)
            result["confidence"] = "low"
            result["precise"] = False

        candidates = [item for item in potential_zone_overrides(province, district)
                      if local_rule_active(item, filing_date)]
        if candidates:
            alternatives = []
            for item in candidates:
                target = (item["intermediate_court"] if lv["level"] == "中级"
                          else item["basic_court"])
                alternatives.append("若位于%s则为%s" % (item["name"], target))
            result["court"] = "%s；%s" % (result["court"], "；".join(alternatives))
            result["confidence"] = "low"
            result["precise"] = False
            result["extra"] = (result.get("extra", "") +
                               "；仅凭“%s”不能排除特殊园区管辖" % district).strip("；")
            zone_names = "、".join(item["name"] for item in candidates)
            result["warnings"].append(
                "该区或地址可能涉及特殊管辖区域（%s）。必须核对完整地址；确认园区内时传入 %s [园区全名]，"
                "确认园区外时传入 %s。不得仅凭模糊地名判断。"
                % (zone_names, zone_arg, outside_arg))
        return result

    if lv["level"] == "中级":
        legacy_intermediate = ((legacy_override or {}).get("pre_effective_current_snapshot") or {}).get("intermediate_court")
        # 名称能由地级市唯一确定时 precise 为真。多家中院的省级行政区只给占位，
        # 不拼出一个实际上不存在的「某市中级人民法院」。
        if legacy_intermediate:
            court, precise = legacy_intermediate, True
        else:
            multi = multiple_intermediate(province)
            if multi:
                court, precise = multi["label"], False
                warnings.append(multi["warning"])
            else:
                court, precise = inter_name(std_city), True
        warnings.append(
            "信息网络传播权侵权民事案件不属知识产权法院管辖范围，达到中院级别标准的应向普通中级人民法院起诉"
            "（计算机软件著作权案件除外）")
        return finish({"court": court, "level": "中级人民法院", "reason": lv["reason"],
                       "confidence": lv["confidence"], "precise": precise,
                       "extra": extra + "中院为 %s" % court, "warnings": warnings})

    loc = locate_court(province, city, district, parent)
    if loc.get("court"):
        note = "已按“%s”定位" % (loc.get("via") or district or city)
        if loc.get("matched"):
            note += "（该院辖区含：%s）" % loc["matched"]
        if loc.get("match_level") == "parent-fallback":
            # 知产案件集中管辖：县级市通常无独立知产管辖法院，由所属地级市的集中管辖法院受理。
            # 这是制度设计的正常结果，不是数据缺失，不降置信度。
            note += "。知识产权案件实行集中管辖，“%s”无独立知产管辖法院，由所属%s的集中管辖法院受理" % (city, parent)
        return finish({"court": loc["court"], "level": "基层人民法院", "reason": lv["reason"],
                       "confidence": lv["confidence"], "precise": True,
                       "extra": extra + note, "warnings": warnings})
    if loc.get("multi"):
        return finish({"court": norm_city(city) + "市相应基层人民法院", "level": "基层人民法院",
                       "reason": lv["reason"], "confidence": "low", "precise": False,
                       "extra": "该市多个基层法院分片管辖（%s），需补充被告所在区/县/镇街" % "、".join(loc["multi"]),
                       "warnings": warnings + ["未能定位到唯一法院，需补充更细的地址层级"]})
    # 定位失败有两种可能：地名真实但辖区表未收录，或地名本身写错了。
    # 两者的处置完全不同，必须区分开告知，不能都说成「未收录」。
    if not place_known(province, city, district):
        tip = ("未在%s的行政区划表中找到“%s”，请先核对地名是否有误。"
               % (province, district or city))
    else:
        tip = ("该地辖区名单未收录，无法锁定具体法院。可查最高人民法院知产案件管辖文件附件、"
               "拨打 12368，或通过『人民法院在线服务』网上立案由系统按被告地址自动路由")
    return finish({"court": (norm_city(city) + "市" if city else "被告所在地") + "有知产管辖权的基层人民法院",
                   "level": "基层人民法院", "reason": lv["reason"], "confidence": "low", "precise": False,
                   "extra": "", "warnings": warnings + [tip]})


# ---------- 管辖方案 ----------

def build_options(inp):
    """列出原告可选的全部管辖通道。"""
    opts = []
    amount = inp["amount"]
    fo = inp.get("is_foreign", False)

    if inp.get("def_prov"):
        r = court_for_place(inp["def_prov"], inp.get("def_city", ""), inp.get("def_district", ""), amount, fo,
                            inp.get("def_zone", ""), inp.get("def_no_special_zone", False),
                            inp.get("filing_date", ""), "--def-zone", "--def-no-special-zone")
        opts.append(_mk("被告住所地", r,
                        "被告住所地人民法院管辖（%s）。%s" % (BASIS_VENUE, r["reason"]),
                        "最稳妥通道，管辖异议风险最低。"))

    if inp.get("server_city"):
        r = court_for_place(inp.get("server_prov"), inp["server_city"],
                            inp.get("server_district", ""), amount, fo,
                            inp.get("server_zone", ""), inp.get("server_no_special_zone", False),
                            inp.get("filing_date", ""), "--server-zone", "--server-no-special-zone")
        opts.append(_mk("侵权行为地（服务器/设备所在地）", r,
                        "以实施被诉侵权行为的网络服务器、计算机终端等设备所在地为侵权行为地（%s）。%s" % (BASIS_VENUE, r["reason"]),
                        "需举证服务器/设备确在该地；被告常以此为由提管辖异议，证据要提前固定。"))

    if inp.get("def_abroad") and inp.get("pl_city"):
        r = court_for_place(inp.get("pl_prov"), inp["pl_city"], inp.get("pl_district", ""), amount, fo,
                            inp.get("pl_zone", ""), inp.get("pl_no_special_zone", False),
                            inp.get("filing_date", ""), "--pl-zone", "--pl-no-special-zone")
        opts.append(_mk("原告发现地（兜底）", r,
                        "被告住所地与侵权行为地均难以确定或在境外的，原告发现侵权内容的计算机终端等设备所在地"
                        "可以视为侵权行为地（%s后段）。%s" % (BASIS_VENUE, r["reason"]),
                        "适用前提严格：须确实无法确定被告住所地和侵权行为地，否则极易被裁定移送。"))

    seen, uniq = set(), []
    for o in opts:
        k = (o["channel"], o["court"])
        if k not in seen:
            seen.add(k)
            uniq.append(o)
    return uniq


def _mk(channel, r, basis, strategy):
    if not r["precise"]:
        strategy = strategy + " 当前尚未锁定到唯一法院，补齐地址或特别区域状态前不要在文书中写死法院名。"
    out = {"channel": channel, "court": r["court"], "level": r["level"],
           "confidence": r["confidence"], "precise": r["precise"],
           "reason": r["reason"], "basis": basis, "strategy": strategy,
           "note": r.get("extra", ""), "warnings": r.get("warnings", [])}
    if r.get("special_rule"):
        out["special_rule"] = r["special_rule"]
    return out


def analyze(inp):
    try:
        amount = float(inp.get("amount", 0))
    except (TypeError, ValueError):
        amount = 0
    if amount <= 0:
        return {"error": "必须提供大于0的诉讼请求标的额（元）；缺少标的额时无法判断基层、中院或高院级别管辖。",
                "input": inp, "options": [], "overall_confidence": "low", "warnings": []}
    inp["amount"] = amount

    if inp.get("filing_date"):
        try:
            filed = date.fromisoformat(str(inp["filing_date"]))
        except ValueError:
            return {"error": "正式立案日期格式无效，请使用 YYYY-MM-DD（例如 2026-08-06）。",
                    "input": inp, "options": [], "overall_confidence": "low", "warnings": []}
        if filed < date(2025, 11, 1):
            return {"error": "本引擎只实现2025-11-01起的现行互联网法院规则与现行辖区表；"
                             "更早受理的案件须按当时规则另行复原，不能用当前表倒推。",
                    "input": inp, "options": [], "overall_confidence": "low", "warnings": []}
    for prefix in ("def", "server", "pl"):
        if inp.get(prefix + "_zone") and inp.get(prefix + "_no_special_zone"):
            return {"error": "%s 连接点不能同时声明位于特殊园区和不在特殊园区。"
                             "请在 --%s-zone 与 --%s-no-special-zone 中二选一。"
                             % (prefix, prefix, prefix),
                    "input": inp, "options": [], "overall_confidence": "low", "warnings": []}
    for key in ("def_prov", "server_prov", "pl_prov"):
        if inp.get(key):
            fixed = norm_province(inp[key])
            if fixed is None:
                return {"error": "无法识别省级行政区「%s」。请填写规范的省/直辖市/自治区名称，"
                                 "如「浙江省」「北京市」「内蒙古自治区」。" % inp[key],
                        "input": inp, "options": [], "overall_confidence": "low", "warnings": []}
            inp[key] = fixed

    for prefix, label in (("server", "侵权行为地"), ("pl", "原告发现地")):
        has_place = any(inp.get(prefix + "_" + part) for part in ("city", "district", "zone"))
        if has_place and not inp.get(prefix + "_prov"):
            flag = "--%s-prov" % prefix
            return {"error": "已填写%s，但没有 %s。不能用被告所在省代替，否则会在错误的省表里查法院。"
                             % (label, flag),
                    "input": inp, "options": [], "overall_confidence": "low", "warnings": []}

    for prefix in ("def", "server", "pl"):
        zone = inp.get(prefix + "_zone")
        if not zone:
            continue
        province = inp.get(prefix + "_prov") or inp.get("def_prov")
        state, item = resolve_zone(province, zone, False)
        if state != "special":
            return {"error": "未识别特殊园区“%s”，不得据此套用特别管辖。请核对园区全名；"
                             "如尚未确认园区归属，请不要传 --%s-zone。" % (zone, prefix),
                    "input": inp, "options": [], "overall_confidence": "low", "warnings": []}
        city = inp.get(prefix + "_city", "")
        if item.get("city") and city and norm_city(city) != norm_city(item["city"]):
            return {"error": "特殊园区“%s”与所填城市“%s”相互冲突。请核对连接点地址。"
                             % (item["name"], city),
                    "input": inp, "options": [], "overall_confidence": "low", "warnings": []}
        district = inp.get(prefix + "_district", "")
        if district:
            # 区县字段必须是规范区县名。这里不能复用 area_hit 的包含匹配，
            # 否则“河西区南开区”等复合/错误文本会绕过冲突校验。
            compatible = any(norm_area(allowed) == norm_area(district)
                             for allowed in item.get("affected_districts", []))
            if not compatible:
                return {"error": "特殊园区“%s”与所填区县“%s”相互冲突。"
                                 "请核对完整地址；若工商地址只写功能区，可暂不填区县，但不得强行套用园区规则。"
                                 % (item["name"], district),
                        "input": inp, "options": [], "overall_confidence": "low", "warnings": []}

    opts = build_options(inp)
    all_w = []
    for o in opts:
        for w in o["warnings"]:
            if w not in all_w:
                all_w.append(w)
    conf = [o["confidence"] for o in opts]
    overall = "low" if (not opts or "low" in conf) else ("medium" if "medium" in conf else "high")
    result = {"input": inp, "options": opts, "overall_confidence": overall,
              "warnings": all_w,
              "amount_yuan": amount, "amount_display": fmt_wan(amount),
              "disclaimer": "本结论由查表计算得出。全国标的额门槛与基层辖区名单据法〔2025〕167号附件"
                          "（2025-09-23 发布，2025-10-01 施行；同时废止法〔2022〕109号）；"
                          "经批准的局部区域调整另据 data/local_venue_overrides.json。"
                          "立案前应复核标的法院当期立案口径及特殊区域边界。"}
    return result


# ---------- 输出 ----------

def emit(text):
    """输出到 stdout，兼容 Windows GBK 控制台与管道两种场景。

    终端场景按终端编码输出（CMD 默认 GBK 代码页也能正常显示中文）；
    重定向或管道场景（AI 调用）强制 UTF-8，保证调用方按 UTF-8 解析不乱码。
    """
    if sys.stdout.isatty():
        enc = sys.stdout.encoding or "utf-8"
        try:
            text.encode(enc)
            print(text)
            return
        except (UnicodeEncodeError, LookupError):
            pass
    sys.stdout.buffer.write((text + "\n").encode("utf-8"))
    sys.stdout.buffer.flush()


def to_text(res):
    if res.get("error"):
        return "输入有误：" + res["error"]
    L = []
    amt = (res.get("input") or {}).get("amount")
    if isinstance(amt, (int, float)) and amt > 0:
        shown = int(amt) if amt == int(amt) else amt
        L.append("标的额：%s 元（%s）" % (shown, res.get("amount_display") or fmt_wan(amt)))
    L.append("信息网络传播权纠纷 · 一审管辖分析")
    L.append("整体置信度：%s" % {"high": "高", "medium": "中", "low": "低"}[res["overall_confidence"]])
    L.append("")
    if not res["options"]:
        L.append("未能生成任何管辖方案：请至少提供被告住所地所在省、市。")
        return "\n".join(L)
    for i, o in enumerate(res["options"], 1):
        L.append("方案 %d · %s" % (i, o["channel"]))
        L.append("  法院：%s（%s）" % (o["court"], o["level"]))
        L.append("  依据：%s" % o["basis"])
        if o["note"]:
            L.append("  定位：%s" % o["note"])
        if o.get("special_rule"):
            L.append("  特别规则来源：%s" % o["special_rule"]["source_url"])
        L.append("  策略：%s" % o["strategy"])
        L.append("  置信度：%s%s" % ({"high": "高", "medium": "中", "low": "低"}[o["confidence"]],
                                     "" if o["precise"] else "（未锁定到唯一法院）"))
        L.append("")
    if res["warnings"]:
        L.append("!! 风险提示")
        for w in res["warnings"]:
            L.append("  · %s" % w)
    L.append("")
    L.append(res["disclaimer"])
    return "\n".join(L)


# ---------- 自检 ----------

def selftest():
    cases = [
        # 法释〔2025〕14号（2025-11-01 施行）后，网络著作权案件不再由互联网法院管辖
        ("北京案件不得路由到互联网法院",
         {"def_prov": "北京市", "def_city": "北京市", "def_district": "朝阳区", "amount": 500_000},
         lambda r: "互联网法院" not in r["options"][0]["court"]),
        ("杭州案件不得路由到互联网法院",
         {"def_prov": "浙江省", "def_city": "杭州市", "def_district": "西湖区", "amount": 800_000},
         lambda r: "互联网法院" not in r["options"][0]["court"]),
        ("广州案件不得路由到互联网法院",
         {"def_prov": "广东省", "def_city": "广州市", "def_district": "天河区", "amount": 800_000},
         lambda r: "互联网法院" not in r["options"][0]["court"]),
        ("浙江超500万应升中院，且不得走知产法院",
         {"def_prov": "浙江省", "def_city": "杭州市", "def_district": "西湖区", "amount": 6_000_000},
         lambda r: r["options"][0]["court"] == "杭州市中级人民法院"
                   and r["options"][0]["level"] == "中级人民法院"
                   and r["options"][0]["precise"] is True
                   and r["options"][0]["confidence"] == "medium"
                   and "知识产权法院" not in r["options"][0]["court"]),
        ("京沪 noCap：标的额再大也留在基层",
         {"def_prov": "上海市", "def_city": "上海市", "def_district": "浦东新区", "amount": 20_000_000},
         lambda r: r["options"][0]["level"] == "基层人民法院"),
        ("宁夏标的额已据附件核实，不应再作推定值降级",
         {"def_prov": "宁夏回族自治区", "def_city": "银川市", "def_district": "兴庆区", "amount": 500_000},
         lambda r: r["options"][0]["confidence"] == "medium"
                   and not any("推定" in w for w in r["warnings"])),
        ("31 个省级行政区的标的额门槛均有明确出处，无推定值",
         {"def_prov": "浙江省", "def_city": "杭州市", "def_district": "西湖区", "amount": 800_000},
         lambda r: all(v.get("cap_status") == "sourced" for v in PROVINCES.values())),
        ("县级市按知产集中管辖归位到地级市法院，且结论精确",
         {"def_prov": "辽宁省", "def_city": "开原市", "amount": 500_000},
         lambda r: r["options"][0]["precise"] is True
                   and "集中管辖" in r["options"][0]["note"]),
        ("常规省份正常命中应为 medium 置信度",
         {"def_prov": "江苏省", "def_city": "苏州市", "def_district": "虎丘区", "amount": 500_000},
         lambda r: r["options"][0]["precise"] is True
                   and r["options"][0]["confidence"] == "medium"),
        ("广东分档：深圳按重点城市 1000 万档，600 万仍在基层",
         {"def_prov": "广东省", "def_city": "深圳市", "def_district": "南山区", "amount": 6_000_000},
         lambda r: r["options"][0]["level"] == "基层人民法院"),
        ("以「州」结尾的普通地级市，中院名须含「市」",
         {"def_prov": "江苏省", "def_city": "苏州市", "def_district": "虎丘区", "amount": 8_000_000},
         lambda r: r["options"][0]["court"] == "苏州市中级人民法院"
                   and r["options"][0]["precise"] is True),
        ("自治州中院名不含「市」",
         {"def_prov": "吉林省", "def_city": "延吉市", "amount": 5_000_000},
         lambda r: r["options"][0]["court"].endswith("自治州中级人民法院")),
        ("中山镇区细分：小榄归第二人民法院",
         {"def_prov": "广东省", "def_city": "中山市", "def_district": "小榄", "amount": 500_000},
         lambda r: r["options"][0]["court"] == "中山市第二人民法院"),
        ("省份简称「浙江」应能识别，不退化为未收录",
         {"def_prov": "浙江", "def_city": "杭州市", "def_district": "西湖区", "amount": 800_000},
         lambda r: r["options"][0]["court"] == "杭州市西湖区人民法院"
                   and r["options"][0]["confidence"] == "medium"),
        ("自治区简称「内蒙古」应能识别",
         {"def_prov": "内蒙古", "def_city": "呼和浩特市", "amount": 500_000},
         lambda r: not r.get("error")),
        ("无效省名必须报错，不得编造法院",
         {"def_prov": "火星省", "def_city": "火星市", "amount": 500_000},
         lambda r: bool(r.get("error")) and not r["options"]),
        ("未提供标的额时必须中止，不得输出唯一法院",
         {"def_prov": "浙江省", "def_city": "杭州市", "def_district": "西湖区", "amount": 0},
         lambda r: bool(r.get("error")) and not r["options"]),
        ("地名写错时应提示核对地名，而非笼统说未收录",
         {"def_prov": "浙江省", "def_city": "不存在市", "amount": 500_000},
         lambda r: any("核对地名" in x for x in r["warnings"])),
        ("被告在境外时才出现原告发现地兜底方案",
         {"def_prov": "浙江省", "def_city": "杭州市", "amount": 500_000,
          "def_abroad": True, "pl_prov": "浙江省", "pl_city": "宁波市"},
         lambda r: any(o["channel"].startswith("原告发现地") for o in r["options"])),
        ("天津华苑科技园低于500万应由滨海新区法院管辖",
         {"def_prov": "天津市", "def_city": "天津市", "def_district": "南开区",
          "def_zone": "华苑科技园", "amount": 4_999_999},
         lambda r: r["options"][0]["court"] == "天津市滨海新区人民法院"
                   and r["options"][0]["precise"] is True
                   and "499.9999万元" in r["options"][0]["reason"]
                   and r["options"][0].get("special_rule", {}).get("id") == "tianjin_huayuan_science_park_2026"),
        ("天津华苑科技园正好500万应由天津三中院管辖",
         {"def_prov": "天津市", "def_city": "天津市", "def_district": "西青区",
          "def_zone": "天津滨海高新区华苑科技园", "amount": 5_000_000},
         lambda r: r["options"][0]["court"] == "天津市第三中级人民法院"
                   and r["options"][0]["precise"] is True),
        ("天津华苑科技园正好50亿元应由天津高院而非三中院管辖",
         {"def_prov": "天津市", "def_city": "天津市", "def_district": "西青区",
          "def_zone": "华苑科技园", "amount": 5_000_000_000},
         lambda r: r["options"][0]["court"] == "天津市高级人民法院"
                    and r["options"][0]["level"] == "高级人民法院"
                    and r["options"][0]["precise"] is True),
        ("天津华苑科技园低于50亿元1元仍由天津三中院管辖",
         {"def_prov": "天津市", "def_city": "天津市", "def_district": "西青区",
          "def_zone": "华苑科技园", "amount": 4_999_999_999},
         lambda r: r["options"][0]["court"] == "天津市第三中级人民法院"
                   and r["options"][0]["precise"] is True),
        ("天津华苑科技园公告前已立案案件继续由原基层法院审理",
         {"def_prov": "天津市", "def_city": "天津市", "def_district": "南开区",
          "def_zone": "华苑科技园", "filing_date": "2026-08-05", "amount": 500_000},
         lambda r: r["options"][0]["court"] == "天津市南开区人民法院"
                   and r["options"][0]["precise"] is True
                   and any("原管辖法院" in w for w in r["warnings"])),
        ("天津华苑科技园公告发布当日新立案适用新规则",
         {"def_prov": "天津市", "def_city": "天津市", "def_district": "南开区",
          "def_zone": "华苑科技园", "filing_date": "2026-08-06", "amount": 500_000},
         lambda r: r["options"][0]["court"] == "天津市滨海新区人民法院"),
        ("天津华苑科技园公告前中院档旧案继续由天津一中院审理",
         {"def_prov": "天津市", "def_city": "天津市", "def_district": "西青区",
          "def_zone": "华苑科技园", "filing_date": "2026-08-05", "amount": 5_000_000},
         lambda r: r["options"][0]["court"] == "天津市第一中级人民法院"
                   and r["options"][0]["precise"] is True),
        ("无效立案日期必须报错",
         {"def_prov": "天津市", "def_city": "天津市", "filing_date": "2026-02-30", "amount": 500_000},
         lambda r: bool(r.get("error")) and not r["options"]),
        ("早于现行规则快照的旧案不得用当前表倒推",
         {"def_prov": "天津市", "def_city": "天津市", "filing_date": "2025-10-31", "amount": 500_000},
         lambda r: bool(r.get("error")) and not r["options"]),
        ("天津南开区未核实是否在园区时不得写死法院",
         {"def_prov": "天津市", "def_city": "天津市", "def_district": "南开区", "amount": 500_000},
         lambda r: r["options"][0]["precise"] is False
                   and r["options"][0]["confidence"] == "low"
                   and "天津市南开区人民法院" in r["options"][0]["court"]
                   and "天津市滨海新区人民法院" in r["options"][0]["court"]),
        ("天津西青区未核实是否在园区时不得写死法院",
         {"def_prov": "天津市", "def_city": "天津市", "def_district": "西青区", "amount": 500_000},
         lambda r: r["options"][0]["precise"] is False
                   and r["options"][0]["confidence"] == "low"
                   and "天津市和平区人民法院" in r["options"][0]["court"]
                   and "天津市滨海新区人民法院" in r["options"][0]["court"]),
        ("天津南开区已核实园区外时仍按南开法院精确路由",
         {"def_prov": "天津市", "def_city": "天津市", "def_district": "南开区",
          "def_no_special_zone": True, "amount": 500_000},
         lambda r: r["options"][0]["court"] == "天津市南开区人民法院"
                   and r["options"][0]["precise"] is True),
        ("天津西青区已核实园区外时仍按和平法院精确路由",
         {"def_prov": "天津市", "def_city": "天津市", "def_district": "西青区",
          "def_no_special_zone": True, "amount": 500_000},
         lambda r: r["options"][0]["court"] == "天津市和平区人民法院"
                   and r["options"][0]["precise"] is True),
        ("服务器连接点位于华苑科技园时同样适用特别路由",
         {"def_prov": "浙江省", "def_city": "杭州市", "def_district": "西湖区",
          "server_prov": "天津市", "server_city": "天津市", "server_district": "西青区",
          "server_zone": "华苑科技园", "amount": 500_000},
         lambda r: any(o["channel"].startswith("侵权行为地")
                       and o["court"] == "天津市滨海新区人民法院" for o in r["options"])),
        ("服务器连接点已确认园区外时按普通分片精确路由",
         {"def_prov": "浙江省", "def_city": "杭州市", "def_district": "西湖区",
          "server_prov": "天津市", "server_city": "天津市", "server_district": "南开区",
          "server_no_special_zone": True, "amount": 500_000},
         lambda r: any(o["channel"].startswith("侵权行为地")
                       and o["court"] == "天津市南开区人民法院"
                       and o["precise"] is True for o in r["options"])),
        ("服务器连接点园区状态未知时不得写死法院",
         {"def_prov": "浙江省", "def_city": "杭州市", "def_district": "西湖区",
          "server_prov": "天津市", "server_city": "天津市", "server_district": "南开区",
          "amount": 500_000},
         lambda r: any(o["channel"].startswith("侵权行为地")
                       and o["precise"] is False
                       and "天津市滨海新区人民法院" in o["court"] for o in r["options"])),
        ("原告发现地位于华苑科技园时同样适用特别路由",
         {"def_prov": "浙江省", "def_city": "杭州市", "amount": 500_000,
          "def_abroad": True, "pl_prov": "天津市", "pl_city": "天津市", "pl_district": "南开区",
          "pl_zone": "华苑科技园"},
         lambda r: any(o["channel"].startswith("原告发现地")
                       and o["court"] == "天津市滨海新区人民法院" for o in r["options"])),
        ("复合地址含华苑科技园但未显式确认时不得被宽松匹配写死",
         {"def_prov": "天津市", "def_city": "天津市", "def_district": "南开区华苑科技园", "amount": 500_000},
         lambda r: r["options"][0]["precise"] is False
                   and r["options"][0]["confidence"] == "low"),
        ("含南开区名但不含园区别名的复合地址仍须核验园区状态",
         {"def_prov": "天津市", "def_city": "天津市", "def_district": "南开区华苑街道某号", "amount": 500_000},
         lambda r: r["options"][0]["precise"] is False
                   and r["options"][0]["confidence"] == "low"),
        ("普通滨海新区输入不受华苑科技园例外影响",
         {"def_prov": "天津市", "def_city": "天津市", "def_district": "滨海新区", "amount": 500_000},
         lambda r: r["options"][0]["court"] == "天津市滨海新区人民法院"
                   and r["options"][0]["precise"] is True),
        ("天津普通区域达到500万不得编造单一天津市中级人民法院",
         {"def_prov": "天津市", "def_city": "天津市", "def_district": "河西区", "amount": 5_000_000},
         lambda r: r["options"][0]["court"] == "天津市有管辖权的中级人民法院"
                   and r["options"][0]["precise"] is False),
        ("特殊园区与园区外断言互斥",
         {"def_prov": "天津市", "def_city": "天津市", "def_district": "南开区",
          "def_zone": "华苑科技园", "def_no_special_zone": True, "amount": 500_000},
         lambda r: bool(r.get("error")) and not r["options"]),
        ("特殊园区与区县冲突时必须报错",
         {"def_prov": "天津市", "def_city": "天津市", "def_district": "河西区",
          "def_zone": "华苑科技园", "amount": 500_000},
         lambda r: bool(r.get("error")) and not r["options"]),
        ("复合错误区县不得绕过特殊园区冲突校验",
         {"def_prov": "天津市", "def_city": "天津市", "def_district": "河西区南开区",
          "def_zone": "华苑科技园", "amount": 500_000},
         lambda r: bool(r.get("error")) and not r["options"]),
        ("特殊园区与错误城市冲突时必须报错",
         {"def_prov": "天津市", "def_city": "北京市", "def_zone": "华苑科技园", "amount": 500_000},
         lambda r: bool(r.get("error")) and not r["options"]),
        ("未识别园区在高院标的额下也必须报错",
         {"def_prov": "天津市", "def_city": "天津市", "def_district": "南开区",
          "def_zone": "华苑科枝园", "amount": 5_000_000_000},
         lambda r: bool(r.get("error")) and not r["options"]),
        ("华苑中院上限数据必须与天津高院起点保持一致",
         {"def_prov": "天津市", "def_city": "天津市", "def_district": "南开区",
          "def_no_special_zone": True, "amount": 500_000},
         lambda r: LOCAL_OVERRIDES["zones"][0]["intermediate_upper_exclusive"]
                   == PROVINCES["天津市"]["high_court_min"]),
        ("文本输出第一行同时给出元和万元",
         {"def_prov": "浙江省", "def_city": "杭州市", "def_district": "西湖区", "amount": 800_000},
         lambda r: to_text(r).startswith("标的额：800000 元（80万元）")
                   and r["amount_yuan"] == 800_000
                   and r["amount_display"] == "80万元"),
        ("不足1万元不得维持中等置信度",
         {"def_prov": "浙江省", "def_city": "杭州市", "def_district": "西湖区", "amount": 100},
         lambda r: r["options"][0]["confidence"] == "low"
                   and r["options"][0]["court"] == "杭州市西湖区人民法院"
                   and any("1000000" in w and "万元" in w for w in r["warnings"])),
        ("重庆多家中院时不得拼出不存在的重庆市中级人民法院",
         {"def_prov": "重庆市", "def_city": "重庆市", "def_district": "渝中区", "amount": 6_000_000},
         lambda r: r["options"][0]["court"] == "重庆市有管辖权的中级人民法院"
                   and r["options"][0]["precise"] is False
                   and "重庆市中级人民法院" not in r["options"][0]["court"]),
        ("未收录高院起点且标的额达50亿元时不锁定中院",
         {"def_prov": "广东省", "def_city": "深圳市", "def_district": "南山区", "amount": 5_000_000_000},
         lambda r: r["options"][0]["precise"] is False
                   and r["options"][0]["confidence"] == "low"
                   and r["options"][0]["court"] == "广东省有管辖权的中级人民法院或高级人民法院"
                   and "深圳市中级人民法院" not in r["options"][0]["court"]),
        ("50亿元降级线以下仍锁定唯一中院",
         {"def_prov": "广东省", "def_city": "深圳市", "def_district": "南山区", "amount": 20_000_000},
         lambda r: r["options"][0]["court"] == "深圳市中级人民法院"
                   and r["options"][0]["precise"] is True
                   and r["options"][0]["confidence"] == "medium"),
        ("侵权行为地缺少省级时必须报错，不得改用被告所在省",
         {"def_prov": "浙江省", "def_city": "杭州市", "def_district": "西湖区",
          "server_city": "天津市", "amount": 500_000},
         lambda r: bool(r.get("error")) and not r["options"] and "server-prov" in r["error"]),
        ("基层法院共570家，court_entries是辖区格数不是法院家数",
         {"def_prov": "浙江省", "def_city": "杭州市", "def_district": "西湖区", "amount": 800_000},
         lambda r: sum(len(v.get("courts", [])) for v in COURTS.values()) == 570
                   and all(
                       sum(len(ct.get("a", [])) for ct in COURTS.get(name, {}).get("courts", []))
                       == meta.get("court_entries")
                       for name, meta in PROVINCES.items())),
    ]
    ok = 0
    for name, inp, check in cases:
        try:
            r = analyze(inp)
            passed = check(r)
        except Exception as e:                                  # noqa: BLE001
            passed, r = False, {"error": repr(e)}
        emit(("  PASS  " if passed else "  FAIL  ") + name)
        if not passed:
            emit("        -> " + json.dumps(r, ensure_ascii=False)[:400])
        ok += 1 if passed else 0
    emit("\n%d/%d passed" % (ok, len(cases)))
    return 0 if ok == len(cases) else 1


def main():
    p = argparse.ArgumentParser(description="信息网络传播权纠纷一审管辖判定")
    p.add_argument("--def-prov", dest="def_prov", help="被告住所地·省级")
    p.add_argument("--def-city", dest="def_city", default="", help="被告住所地·地级市")
    p.add_argument("--def-district", dest="def_district", default="", help="被告住所地·区/县")
    g_def_zone = p.add_mutually_exclusive_group()
    g_def_zone.add_argument("--def-zone", dest="def_zone", default="", help="被告住所地·已确认的特殊园区/功能区")
    g_def_zone.add_argument("--def-no-special-zone", dest="def_no_special_zone", action="store_true",
                            help="已核实被告住所地不在特殊管辖园区")
    p.add_argument("--amount", type=float, default=0, help="诉讼请求标的额（元）")
    p.add_argument("--filing-date", dest="filing_date", default="",
                   help="案件正式立案日期 YYYY-MM-DD；省略表示当前准备新立案")
    p.add_argument("--server-prov", dest="server_prov", default="", help="服务器所在地·省级")
    p.add_argument("--server-city", dest="server_city", default="", help="服务器所在地·地级市")
    p.add_argument("--server-district", dest="server_district", default="", help="服务器所在地·区/县")
    g_server_zone = p.add_mutually_exclusive_group()
    g_server_zone.add_argument("--server-zone", dest="server_zone", default="", help="服务器所在地·已确认的特殊园区/功能区")
    g_server_zone.add_argument("--server-no-special-zone", dest="server_no_special_zone", action="store_true",
                               help="已核实服务器所在地不在特殊管辖园区")
    p.add_argument("--pl-prov", dest="pl_prov", default="", help="原告发现地·省级")
    p.add_argument("--pl-city", dest="pl_city", default="", help="原告发现地·地级市")
    p.add_argument("--pl-district", dest="pl_district", default="", help="原告发现地·区/县")
    g_pl_zone = p.add_mutually_exclusive_group()
    g_pl_zone.add_argument("--pl-zone", dest="pl_zone", default="", help="原告发现地·已确认的特殊园区/功能区")
    g_pl_zone.add_argument("--pl-no-special-zone", dest="pl_no_special_zone", action="store_true",
                           help="已核实原告发现地不在特殊管辖园区")
    p.add_argument("--def-abroad", dest="def_abroad", action="store_true", help="被告住所地/侵权行为地在境外或无法确定")
    p.add_argument("--foreign", dest="is_foreign", action="store_true", help="涉外或涉港澳台")
    p.add_argument("--text", action="store_true", help="输出人类可读文本而非 JSON")
    p.add_argument("--selftest", action="store_true", help="运行内置用例自检")
    a = p.parse_args()

    if a.selftest:
        sys.exit(selftest())
    if not a.def_prov:
        p.error("至少需要 --def-prov（被告住所地所在省级行政区）")

    inp = {k: v for k, v in vars(a).items() if k not in ("text", "selftest") and v not in ("", None, False)}
    inp["amount"] = a.amount
    res = analyze(inp)
    out = to_text(res) if a.text else json.dumps(res, ensure_ascii=False, indent=1)
    emit(out)
    if res.get("error"):
        sys.exit(1)


if __name__ == "__main__":
    main()
