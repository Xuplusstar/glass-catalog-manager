"""Zemax AGF / CODE V XML library core and JSON-friendly command line.

Only the Python standard library is required. Original records are retained for
same-format exports; cross-format exports report fields without an equivalent.
"""

from __future__ import annotations

import argparse
from bisect import bisect_left
from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import date
import hashlib
import json
import math
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET


class CatalogError(ValueError):
    """An input or requested conversion cannot be represented correctly."""


EQUATIONS = {1: "Laurent", 2: "Glass Manufacturer Sellmeier", 3: "Herzberger"}
FORMULAS = {value: key for key, value in EQUATIONS.items()}
# This manufacturer's variant has the same six powers of wavelength as Schott.
FORMULAS["Glass Manufacturer Laurent"] = 1
AGF_TO_AVAILABILITY = {0: 1, 1: 0, 2: 3, 3: 2, 4: 8}
AVAILABILITY_TO_AGF = {0: 1, 1: 0, 2: 3, 3: 2, 4: 2, 5: 3, 8: 3}
AGF_STATUS_LABELS = {0: "标准", 1: "优选", 2: "停产", 3: "特殊", 4: "熔批"}
CODEV_AVAILABILITY_LABELS = {
    0: "优选", 1: "标准", 2: "需询价", 3: "停产", 4: "停产（有推荐替代）", 5: "试制", 6: "充分供应",
    7: "有限供应", 8: "请询厂家", 10: "最高熔炼频率", 11: "较高熔炼频率", 12: "低熔炼频率", 14: "很低熔炼频率",
    21: "连续大批量生产", 22: "大批量生产", 23: "经常生产", 24: "偶尔生产", 25: "特殊订货",
}
CODEV_FREQUENCY_LABELS = {10: "最高", 11: "较高", 12: "低", 14: "很低"}
SUPPLY_STATUS_LABELS = {**{f"agf:{key}": f"Zemax · {text}" for key, text in AGF_STATUS_LABELS.items()},
                        **{f"codev:{key}": f"CODE V · {text}" for key, text in CODEV_AVAILABILITY_LABELS.items()}}
AUTO_TRANSMISSION_LIMIT = 1.001  # Up to 100.1%; an export policy, not a measurement correction.


@dataclass
class Glass:
    name: str
    catalog: str
    source: str
    format: str
    formula: int | None = None
    equation: str = ""
    coefficients: list[float | None] = field(default_factory=list)
    nd: float | None = None
    vd: float | None = None
    status: int | None = None
    availability: int | None = None
    melt_frequency: int | None = None
    supplier_grade: str | None = None
    supplier_reference: dict | None = None
    nm_extra: list[float | None] = field(default_factory=list)
    mil: float | None = None
    ed: list[float | None] = field(default_factory=list)
    td: list[float | None] = field(default_factory=list)
    md: list[float | None] = field(default_factory=list)
    od: list[float | None] = field(default_factory=list)
    wavelength_range: tuple[float, float] | None = None
    transmission: list[tuple[float, float, float]] = field(default_factory=list)
    transmission_above_one: list[dict] = field(default_factory=list, repr=False)
    comments: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    agf_header: list[str] = field(default_factory=list, repr=False)
    raw_agf: list[str] = field(default_factory=list, repr=False)
    raw_xml: ET.Element | None = field(default=None, repr=False)
    native_root: ET.Element | None = field(default=None, repr=False)

    @property
    def density(self):
        return self.ed[2] if len(self.ed) > 2 else None

    @property
    def supply_status(self):
        value = self.availability if self.format == "xml" else self.status
        return f"{'codev' if self.format == 'xml' else 'agf'}:{value}" if value is not None else None

    @property
    def supply_label(self):
        labels = CODEV_AVAILABILITY_LABELS if self.format == "xml" else AGF_STATUS_LABELS
        value = self.availability if self.format == "xml" else self.status
        return labels.get(value, "未提供" if value is None else f"未知（{value}）")

    @property
    def melt_frequency_label(self):
        if self.format == "xml":
            return CODEV_FREQUENCY_LABELS.get(self.availability, "未提供")
        value = self.melt_frequency
        return {1: "1 · 很频繁", 2: "2", 3: "3", 4: "4", 5: "5 · 很少"}.get(value, "未提供")

    def summary(self):
        return {"name": self.name, "catalog": self.catalog, "source": self.source,
                "format": self.format, "formula": self.formula, "equation": self.equation,
                "nd": self.nd, "vd": self.vd, "density": self.density,
                "status": self.status, "availability": self.availability,
                "supply_status": self.supply_status, "supply_label": self.supply_label,
                "melt_frequency": self.melt_frequency, "melt_frequency_label": self.melt_frequency_label,
                "supplier_grade": self.supplier_grade, "supplier_reference": self.supplier_reference,
                "wavelength_range_um": self.wavelength_range,
                "transmission_thicknesses_mm": sorted({point[2] for point in self.transmission}),
                "transmission_point_count": len(self.transmission) + len(self.transmission_above_one),
                "transmission_above_one_count": len(self.transmission_above_one),
                "thermal_constants_available": bool(self.td) and None not in self.td,
                "issues": self.issues, "cross_format_supported": can_convert(self)}


@dataclass
class Catalog:
    name: str
    source: str
    format: str
    glasses: list[Glass]
    comments: list[str] = field(default_factory=list)
    encoding: str = ""


def _number(value):
    if value is None or value.strip() in {"", "_", "-", "--", "NONE"}:
        return None
    number = float(value.replace("D", "E").replace("d", "e"))
    if not math.isfinite(number):
        raise CatalogError(f"非有限数值：{value}")
    return number


def _integer(value, label):
    if value is None:
        return None
    if value != int(value):
        raise CatalogError(f"{label} 应为整数，实际为 {value}")
    return int(value)


def _text_number(value):
    return "_" if value is None else format(value, ".17g")


def _decode_agf(data):
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16"), "utf-16"
    if data.startswith(b"\xef\xbb\xbf"):
        return data.decode("utf-8-sig"), "utf-8-sig"
    # Many vendor AGFs predate Unicode; only decoding is retried here.
    try:
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        return data.decode("cp1252"), "cp1252"


def _agf_numbers(parts, glass, tag):
    values = []
    for text in parts:
        if re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eEdD][+-]?\d+)?", text):
            values.append(_number(text))
        else:
            values.append(None)
            if text not in {"_", "-", "--"}:
                glass.issues.append(f"{tag} 非数值字段 {text!r}：原始记录保留")
    return values


def can_convert(glass, *, automatic_transmission=True):
    handled = {point["issue"] for point in glass.transmission_above_one
               if automatic_transmission and point["original_value"] <= AUTO_TRANSMISSION_LIMIT}
    return (glass.formula in EQUATIONS and len(glass.coefficients) >= 6 and
            None not in glass.coefficients[:6] and
            not any(x not in (0, None) for x in glass.coefficients[6:]) and
            glass.wavelength_range is not None and
            not any(s.startswith(("CD ", "LD ", "IT ", "CTE ", "TD ")) and s not in handled for s in glass.issues))


def load_catalog(path: str | Path) -> Catalog:
    """Read once into common records, retaining all original glass records."""
    path = Path(path).resolve()
    if path.suffix.lower() not in {".agf", ".xml"}:
        raise CatalogError("输入格式应为 Zemax .AGF 或 CODE V .xml；DAT 不是完整玻璃库。")
    data = path.read_bytes()
    if path.suffix.lower() == ".xml":
        return _load_xml(path, data)
    text, encoding = _decode_agf(data)
    catalog = Catalog(path.stem, str(path), "agf", [], encoding=encoding)
    current = None
    header = []
    numeric_tags = {"CD": "coefficients", "ED": "ed", "TD": "td", "MD": "md", "OD": "od"}
    for lineno, original in enumerate(text.splitlines(), 1):
        line = original.strip()
        parts = line.split()
        if not parts:
            if current is not None:
                current.raw_agf.append(original)
            continue
        tag = parts[0].upper()
        if tag == "NM":
            if len(parts) < 6:
                raise CatalogError(f"{path.name}:{lineno} NM 缺少 name / formula / MIL / nd / vd")
            values = [_number(x) for x in parts[2:]]
            formula = _integer(values[0], "色散公式")
            current = Glass(parts[1], catalog.name, str(path), "agf", formula=formula,
                            equation=EQUATIONS.get(formula, f"Zemax formula {formula}"),
                            mil=values[1], nd=values[2], vd=values[3], nm_extra=values[4:], agf_header=header)
            current.status = _integer(values[5], "供应状态") if len(values) > 5 else None
            current.melt_frequency = _integer(values[6], "熔炼频率") if len(values) > 6 else None
            current.availability = AGF_TO_AVAILABILITY.get(current.status, 8)
            catalog.glasses.append(current)
        if current is not None:
            current.raw_agf.append(original)
        else:
            header.append(original)
        if tag == "CC":
            catalog.comments.append(line[2:].strip())
        if current is None or tag.startswith("!"):
            continue
        if tag == "GC":
            current.comments.append(line[2:].strip())
        elif tag in numeric_tags:
            setattr(current, numeric_tags[tag], _agf_numbers(parts[1:], current, tag))
        elif tag == "LD":
            bounds = _agf_numbers(parts[1:], current, tag)
            if len(bounds) != 2 or None in bounds or not 0 < bounds[0] < bounds[1]:
                current.issues.append(f"LD 波长范围无效（第 {lineno} 行），原始记录保留")
            else:
                current.wavelength_range = tuple(bounds)
        elif tag == "IT":
            values = _agf_numbers(parts[1:], current, tag)
            if len(values) != 3 or None in values:
                current.issues.append(f"IT 第 {lineno} 行数据不完整，应为波长(μm)、透过率、厚度(mm)；原始记录保留")
            elif not (values[0] > 0 and values[1] >= 0 and values[2] > 0):
                current.issues.append(f"IT 第 {lineno} 行数据超出物理范围：{line}；原始记录保留")
            elif values[1] > 1:
                issue = (f"IT 第 {lineno} 行：{values[0]*1000:.10g} nm、{values[2]:.10g} mm 的内透过率为 "
                         f"{values[1]*100:.10g}%（原值 {values[1]:.10g}），超过 100%；原始记录保留")
                current.issues.append(issue)
                current.transmission_above_one.append({"wavelength_um": values[0], "original_value": values[1],
                                                       "thickness_mm": values[2], "source_line": lineno, "issue": issue})
            else:
                current.transmission.append(tuple(values))
    if not catalog.glasses:
        raise CatalogError(f"{path.name} 不含 NM 玻璃记录")
    for glass in catalog.glasses:
        if glass.td and (len(glass.td) < 6 or None in glass.td[:min(7, len(glass.td))]):
            glass.issues.append("TD 热光常数记录不完整，原始记录保留")
    return catalog


def _xml_number(node, path):
    return _number(node.findtext(path))


def _load_xml(path, data):
    root = ET.fromstring(data)
    if root.tag != "Catalog" or root.find("Glasses") is None:
        raise CatalogError(f"{path.name} 不是 CODE V Catalog XML")
    name = root.findtext("Name") or path.stem
    catalog = Catalog(name, str(path), "xml", [])
    for node in root.findall("./Glasses/Glass"):
        glass_name = node.findtext("GlassName")
        if not glass_name:
            raise CatalogError(f"{path.name} 中有缺少 GlassName 的记录")
        equation = node.findtext("EquationType", "")
        coefficients = [_number(x.text) for x in node.findall("./DispersionCoefficients/Coefficient")]
        formula = FORMULAS.get(equation)
        if formula in EQUATIONS and len(coefficients) < 6:
            coefficients += [0.0] * (6 - len(coefficients))
        glass = Glass(glass_name, name, str(path), "xml", formula=formula,
                      equation=equation, coefficients=coefficients, raw_xml=node, native_root=root)
        glass.availability = _integer(_xml_number(node, "Availability"), "Availability")
        glass.status = AVAILABILITY_TO_AGF.get(glass.availability, 3)
        low, high = _xml_number(node, "LowWavelength"), _xml_number(node, "HighWavelength")
        if low is not None and high is not None:
            if not 0 < low < high:
                raise CatalogError(f"{glass_name} 的 XML 波长范围无效")
            glass.wavelength_range = (low / 1000, high / 1000)
        density = None
        for prop in node.findall("./ManufacturersProperties/Property"):
            if prop.findtext("Name") == "Specific_grav":
                density = _xml_number(prop, "Value")
        ctes = []
        for tag in ("LowCTE", "HighCTE"):
            block = node.find(tag)
            value = _xml_number(block, "Value") if block is not None else None
            if value is not None:
                factor = block.findtext("ExpansionCoeffFactor", "10e-6")
                if factor in {"10e-7", "1e-7"}:
                    value *= 0.1
                elif factor not in {"10e-6", "1e-6"}:
                    glass.issues.append(f"CTE {tag} 单位 {factor!r} 暂不支持，原始 XML 保留")
                    value = None
            ctes.append(value)
        if density is not None or any(x is not None for x in ctes):
            glass.ed = [*ctes, density, None, 0.0]
        thermal_blocks = node.findall("./DnDtData/DnDtForCategory/DnDtConstants")
        signatures = {tuple(_xml_number(block, t) for t in
                     ("DnDt_D0", "DnDt_D1", "DnDt_D2", "DnDt_E0", "DnDt_E1", "Lambda", "Temperature"))
                      for block in thermal_blocks}
        if len(signatures) == 1:
            glass.td = list(signatures.pop())
            if None in glass.td:
                glass.issues.append("TD 热光常数不完整，原始 XML 保留")
        elif len(signatures) > 1:
            glass.issues.append("TD 不同类别使用不同热光常数，不能合并为单组 AGF TD")
        elif node.findall("./DnDtData/DnDtForCategory/DnDtWavelengthEntry"):
            glass.issues.append("TD 只有温区表而无模型常数，不能直接转换为 AGF TD")
        for curve in node.findall("./TransmissionCurves/Curve"):
            thickness = _xml_number(curve, "Thickness")
            for entry in curve.findall("Transmission"):
                wavelength, trans = _xml_number(entry, "Wavelength"), _xml_number(entry, "Value")
                if None not in (wavelength, trans, thickness):
                    if not (wavelength > 0 and 0 <= trans <= 1 and thickness > 0):
                        glass.issues.append("IT XML 透过率数据超出物理范围，原始 XML 保留")
                    else:
                        glass.transmission.append((wavelength / 1000, trans, thickness))
                else:
                    glass.issues.append("IT XML 透过率记录不完整，原始 XML 保留")
        glass.nd, glass.vd = optical_constants(glass)
        catalog.glasses.append(glass)
    if not catalog.glasses:
        raise CatalogError(f"{path.name} 不含 Glass 记录")
    return catalog


def refractive_index(glass: Glass, wavelength_um: float) -> float:
    """Evaluate supported dispersion exactly, without fitting or extrapolation."""
    if not math.isfinite(wavelength_um) or wavelength_um <= 0:
        raise CatalogError("波长必须为正数，单位 μm")
    if glass.wavelength_range and not glass.wavelength_range[0] <= wavelength_um <= glass.wavelength_range[1]:
        raise CatalogError(f"{glass.name}: {wavelength_um} μm 超出材料色散有效范围")
    if (glass.formula not in EQUATIONS or len(glass.coefficients) < 6 or None in glass.coefficients[:6]
            or any(x not in (0, None) for x in glass.coefficients[6:])):
        raise CatalogError(f"{glass.name}: 暂不支持计算 {glass.equation} 或其系数不完整")
    c = glass.coefficients
    l2 = wavelength_um ** 2
    if glass.formula == 1:
        n2 = c[0] + c[1] * l2 + c[2] / l2 + c[3] / l2**2 + c[4] / l2**3 + c[5] / l2**4
        n = math.sqrt(n2) if n2 > 0 else math.nan
    elif glass.formula == 2:
        denominators = [l2 - c[i] for i in (1, 3, 5)]
        if 0 in denominators:
            raise CatalogError(f"{glass.name}: 波长落在 Sellmeier 极点")
        n2 = 1 + c[0]*l2/denominators[0] + c[2]*l2/denominators[1] + c[4]*l2/denominators[2]
        n = math.sqrt(n2) if n2 > 0 else math.nan
    else:
        if l2 == 0.028:
            raise CatalogError(f"{glass.name}: 波长落在 Herzberger 极点")
        h = 1 / (l2 - 0.028)
        n = c[0] + c[1]*h + c[2]*h*h + c[3]*l2 + c[4]*l2*l2 + c[5]*l2*l2*l2
    if not math.isfinite(n) or n <= 0:
        raise CatalogError(f"{glass.name}: 在 {wavelength_um} μm 折射率无实数正值")
    return n


def optical_constants(glass):
    wavelengths = (0.6562725, 0.5875618, 0.4861327)
    if (glass.formula not in EQUATIONS or len(glass.coefficients) < 6 or None in glass.coefficients[:6]
            or any(x not in (0, None) for x in glass.coefficients[6:])):
        return None, None
    if glass.wavelength_range is None or not all(glass.wavelength_range[0] <= w <= glass.wavelength_range[1] for w in wavelengths):
        return None, None
    nc, nd, nf = [refractive_index(glass, w) for w in wavelengths]
    return nd, (nd - 1) / (nf - nc) if nf > nc else None


def transmission_at(glass, wavelength_nm, thickness_mm):
    """Internal transmission: interpolate within a measured curve, scale thickness.

    Choose the measured thickness closest in ratio among curves covering the
    wavelength. Values at that thickness are linearly interpolated, then scaled
    with Beer–Lambert. No wavelength extrapolation or surface loss is included.
    """
    curves = defaultdict(list)
    for wave, value, thickness in glass.transmission:
        curves[thickness].append((wave * 1000, value))
    for point in glass.transmission_above_one:
        if point["original_value"] <= AUTO_TRANSMISSION_LIMIT:
            curves[point["thickness_mm"]].append((point["wavelength_um"] * 1000, 1.0))
    available = []
    for thickness, points in curves.items():
        points.sort()
        waves = [point[0] for point in points]
        index = bisect_left(waves, wavelength_nm)
        if index < len(waves) and math.isclose(waves[index], wavelength_nm, rel_tol=1e-10):
            value = points[index][1]
        elif 0 < index < len(waves):
            low, high = points[index - 1], points[index]
            fraction = (wavelength_nm - low[0]) / (high[0] - low[0])
            value = low[1] + fraction * (high[1] - low[1])
        else:
            continue
        available.append((abs(math.log(thickness / thickness_mm)), thickness, value))
    if not available:
        return None
    _, measured_thickness, value = min(available)
    return value ** (thickness_mm / measured_thickness)


def select_glasses(glasses, *, name="", nd_min=None, nd_max=None, vd_min=None, vd_max=None,
                   density_min=None, density_max=None, status=None, names=None, catalog=None, convertible_only=False,
                   supply_status=None, melt_frequency=None, supplier_grade=None,
                   transmission_wavelength_nm=None, transmission_thickness_mm=None,
                   transmission_min_percent=None, transmission_max_percent=None):
    """Filter source nd/vd (AGF) or calculated nd/vd (XML); all limits inclusive."""
    for label, low, high in (("nd", nd_min, nd_max), ("Vd", vd_min, vd_max), ("密度", density_min, density_max),
                             ("内透过率", transmission_min_percent, transmission_max_percent)):
        if any(v is not None and not math.isfinite(v) for v in (low, high)):
            raise CatalogError(f"{label} 筛选范围必须是有限数值")
        if low is not None and high is not None and low > high:
            raise CatalogError(f"{label} 下限大于上限")
    statuses = None if status is None else set([status] if isinstance(status, int) else status)
    if statuses is not None and not statuses <= set(range(5)):
        raise CatalogError("供应状态应为 0～4，可同时选择多个")
    supplies = None if supply_status is None else set(supply_status)
    if supplies is not None and not supplies <= SUPPLY_STATUS_LABELS.keys():
        raise CatalogError("原生供应状态应使用 agf:0～4 或 CODE V Availability，例如 codev:10")
    frequencies = None if melt_frequency is None else set(melt_frequency)
    if frequencies is not None and not frequencies <= set(range(1, 6)):
        raise CatalogError("Zemax 熔炼频率等级应为 1～5，可同时选择多个")
    grades = None if supplier_grade is None else {value.upper() for value in supplier_grade}
    if grades is not None and not grades <= {"MA", "A", "B", "C", "D"}:
        raise CatalogError("厂家分级应为 MA/A/B/C/D，可同时选择多个")
    transmission_filter = transmission_min_percent is not None or transmission_max_percent is not None
    transmission_query = transmission_wavelength_nm is not None or transmission_thickness_mm is not None
    if transmission_filter or transmission_query:
        if any(value is None or not math.isfinite(value) or value <= 0
               for value in (transmission_wavelength_nm, transmission_thickness_mm)):
            raise CatalogError("透过率筛选需填写正数波长（nm）和厚度（mm）")
        if any(value is not None and not 0 <= value <= 100
               for value in (transmission_min_percent, transmission_max_percent)):
            raise CatalogError("内透过率筛选上下限须为 0～100%，例如 95 表示 95%")
    wanted = {v.casefold() for v in names} if names is not None else None
    selected = []
    for glass in glasses:
        if convertible_only and not can_convert(glass):
            continue
        if name.casefold() not in glass.name.casefold():
            continue
        if wanted is not None and glass.name.casefold() not in wanted:
            continue
        if catalog is not None and glass.catalog.casefold() != catalog.casefold():
            continue
        if statuses is not None and glass.status not in statuses:
            continue
        if supplies is not None and glass.supply_status not in supplies:
            continue
        if frequencies is not None and (glass.format != "agf" or glass.melt_frequency not in frequencies):
            continue
        if grades is not None and glass.supplier_grade not in grades:
            continue
        bounds = ((glass.nd, nd_min, nd_max), (glass.vd, vd_min, vd_max), (glass.density, density_min, density_max))
        if any((low is not None or high is not None) and
               (value is None or (low is not None and value < low) or (high is not None and value > high))
               for value, low, high in bounds):
            continue
        if transmission_filter:
            value = transmission_at(glass, transmission_wavelength_nm, transmission_thickness_mm)
            if (value is None or
                    (transmission_min_percent is not None and value * 100 < transmission_min_percent) or
                    (transmission_max_percent is not None and value * 100 > transmission_max_percent)):
                continue
        selected.append(glass)
    if wanted is not None:
        missing = wanted - {g.name.casefold() for g in glasses}
        if missing:
            raise CatalogError("指定材料未找到：" + ", ".join(sorted(missing)))
    return selected


def _codev_name(name):
    return re.sub(r"[^A-Za-z0-9_.+]", "_", name.strip().replace("-", ""))


def _check_cross_format(glasses, target):
    unsupported = [g for g in glasses if g.format != target and not can_convert(g, automatic_transmission=False)]
    if unsupported:
        details = "; ".join(f"{g.catalog}/{g.name} ({'; '.join(g.issues[:1]) or g.equation}"
                            f"{'；共 '+str(len(g.issues))+' 条数据提示' if len(g.issues)>1 else ''})" for g in unsupported[:12])
        raise CatalogError(f"{len(unsupported)} 种材料的模型或数据暂不能跨格式导出：{details}。"
                           "请先处理这些源数据，或明确筛除问题材料后再导出；原格式记录仍可保留。")


def _sub(parent, tag, value):
    ET.SubElement(parent, tag).text = str(value)


def _make_glass_xml(glass, name):
    if glass.raw_xml is not None:
        node = deepcopy(glass.raw_xml)
        node.find("GlassName").text = name
        return node
    node = ET.Element("Glass")
    _sub(node, "GlassName", name)
    numeric = "NONE"
    if glass.nd is not None and glass.vd is not None and 1 < glass.nd < 2 and 0 < glass.vd < 100:
        numeric = f"{math.floor((glass.nd-1)*1000+0.5):03d}{math.floor(glass.vd*10+0.5):03d}"
    _sub(node, "NumericName", numeric)
    _sub(node, "EquationType", EQUATIONS[glass.formula])
    if glass.wavelength_range:
        _sub(node, "LowWavelength", _text_number(glass.wavelength_range[0] * 1000))
        _sub(node, "HighWavelength", _text_number(glass.wavelength_range[1] * 1000))
    else:
        raise CatalogError(f"{glass.name} 缺少 LD 有效波段；不能用 OD 猜测范围")
    _sub(node, "DollarSlabPrice", "0")
    _sub(node, "DollarStripPrice", "0")
    today = date.today().strftime("%m/%d/%y")
    for tag in ("ManufactureDate", "ReceivedDate", "IndexChangedDate"):
        _sub(node, tag, today)
    _sub(node, "Availability", glass.availability if glass.availability is not None else 8)
    coeffs = ET.SubElement(node, "DispersionCoefficients")
    for coefficient in glass.coefficients[:6]:
        _sub(coeffs, "Coefficient", _text_number(coefficient))
    if glass.density is not None:
        prop = ET.SubElement(ET.SubElement(node, "ManufacturersProperties"), "Property")
        _sub(prop, "Name", "Specific_grav")
        _sub(prop, "Value", _text_number(glass.density))
        _sub(prop, "Category", "Mechanical")
    for index, tag, low, high in ((0, "LowCTE", -30, 70), (1, "HighCTE", 100, 300)):
        if len(glass.ed) > index and glass.ed[index] is not None:
            block = ET.SubElement(node, tag)
            _sub(block, "LowerTemperatureLimit", low)
            _sub(block, "UpperTemperatureLimit", high)
            _sub(block, "Value", _text_number(glass.ed[index]))
            _sub(block, "ExpansionCoeffFactor", "10e-6")
    if glass.transmission:
        curves = ET.SubElement(node, "TransmissionCurves")
        by_thickness = defaultdict(list)
        for wavelength, trans, thickness in glass.transmission:
            by_thickness[thickness].append((wavelength, trans))
        for thickness, values in sorted(by_thickness.items()):
            curve = ET.SubElement(curves, "Curve")
            _sub(curve, "Category", "Visible")
            _sub(curve, "Thickness", _text_number(thickness))
            for wavelength, trans in sorted(values):
                entry = ET.SubElement(curve, "Transmission")
                _sub(entry, "Wavelength", _text_number(wavelength * 1000))
                _sub(entry, "Value", _text_number(trans))
    if len(glass.td) >= 6 and None not in glass.td[:6] and any(glass.td[:6]):
        category = ET.SubElement(ET.SubElement(node, "DnDtData"), "DnDtForCategory")
        _sub(category, "Category", "Visible")
        block = ET.SubElement(category, "DnDtConstants")
        tags = ("DnDt_D0", "DnDt_D1", "DnDt_D2", "DnDt_E0", "DnDt_E1", "Lambda", "Temperature")
        td = glass.td[:7] if len(glass.td) >= 7 else [*glass.td[:6], 20.0]
        for tag, value in zip(tags, td):
            if value is not None:
                _sub(block, tag, _text_number(value))
    return node


def _merge_xml_metadata(root, glasses):
    """Keep native catalog-wide category definitions when combining catalogs."""
    roots = {g.source: g.native_root for g in glasses if g.native_root is not None}
    properties = ET.SubElement(root, "CatalogProperties")
    temperatures = set()
    for source_root in roots.values():
        if source_root.findtext("./CatalogProperties/DispersionTemperatureIsSameForAllGlasses") == "false":
            raise CatalogError("含逐材料色散温度的原生 XML 暂不能与其他来源合并；请先单独筛选导出")
        value = source_root.findtext("./CatalogProperties/DispersionTemperature")
        if value:
            temperatures.add(float(value))
    if any(g.format == "agf" for g in glasses):
        temperatures.add(20.0)
    if len(temperatures) > 1:
        raise CatalogError("源库采用不同色散参考温度，请分别导出，不能静默统一为 20°C")
    for source_root in roots.values():
        source_props = source_root.find("CatalogProperties")
        if source_props is None:
            continue
        for child in source_props:
            if child.tag.startswith("DispersionTemperature"):
                continue
            category = child.findtext("Category")
            existing = next((x for x in properties if x.tag == child.tag and x.findtext("Category") == category), None)
            if existing is None:
                properties.append(deepcopy(child))
            elif child.tag in {"CatalogDnDtData", "CatalogTransmissionData"}:
                signatures = {ET.tostring(x, encoding="unicode").strip() for x in existing}
                for entry in child:
                    signature = ET.tostring(entry, encoding="unicode").strip()
                    if entry.tag != "Category" and signature not in signatures:
                        existing.append(deepcopy(entry))
                        signatures.add(signature)
            elif ET.tostring(existing) != ET.tostring(child):
                raise CatalogError(f"源 XML 的 {child.tag} 属性冲突，请分别导出")
    _sub(properties, "DispersionTemperatureIsSameForAllGlasses", "true")
    _sub(properties, "DispersionTemperature", _text_number(next(iter(temperatures), 20.0)))


def _agf_record(glass, name):
    if glass.raw_agf:
        records = list(glass.raw_agf)
        parts = records[0].split()
        parts[1] = name
        records[0] = " ".join(parts)
        return records
    nd = glass.nd if glass.nd is not None else 1.0
    vd = glass.vd if glass.vd is not None else 0.0
    # nd/vd in NM are reference values; coefficients remain authoritative.
    records = [f"NM {name} {glass.formula} 0 {_text_number(nd)} {_text_number(vd)} 0 {glass.status} -1",
               f"GC Converted from CODE V {glass.catalog}/{glass.name}"]
    if glass.ed:
        records.append("ED " + " ".join(_text_number(v if v is not None else 0.0) for v in glass.ed))
    records.append("CD " + " ".join(_text_number(v) for v in glass.coefficients[:6]))
    if glass.td and None not in glass.td:
        records.append("TD " + " ".join(_text_number(v) for v in glass.td))
    if glass.wavelength_range:
        records.append("LD " + " ".join(_text_number(v) for v in glass.wavelength_range))
    else:
        raise CatalogError(f"{glass.name} 缺少有效波段，不能建立完整 AGF 记录")
    # AGF supports up to 100 IT points per glass. Never truncate silently.
    points = sorted(set(glass.transmission))
    if len(points) > 100:
        raise CatalogError(f"{glass.name} 有 {len(points)} 个透过率点，超过 AGF 100 点；请先选择厚度或透过率数据处理策略")
    by_wave = Counter(w for w, _, _ in points)
    if any(count > 1 for count in by_wave.values()):
        raise CatalogError(f"{glass.name} 含多厚度透过率曲线，请用 --transmission-thickness 明确选择 mm 厚度")
    for point in points:
        records.append("IT " + " ".join(_text_number(v) for v in point))
    return records


def export_catalog(glasses: list[Glass], output: str | Path, *, catalog_name=None,
                   prefix_source=False, transmission_thickness=None, write_report=True, selection_info=None,
                   cap_transmission_at_one=False, automatic_transmission=True, codev_root=None, bundle_dir=None,
                   install_codev=False, expert_reference="source"):
    """Export a catalog, optionally preparing and installing its CODE V tables."""
    output = Path(output).resolve()
    target = output.suffix.lower().lstrip(".")
    if target == "dat":
        from glass_expert import export_expert_dat
        return export_expert_dat(glasses, output, catalog_name=catalog_name, prefix_source=prefix_source,
                                 reference=expert_reference, codev_root=codev_root, install_codev=install_codev,
                                 selection_info=selection_info, bundle_dir=bundle_dir, write_report=write_report)
    if target not in {"agf", "xml"}:
        raise CatalogError("输出扩展名应为 .AGF、.xml 或 Glass Expert .dat")
    if codev_root is not None and target != "xml":
        raise CatalogError("CODE V 配套目录仅用于 XML 导出")
    if bundle_dir is not None and codev_root is None:
        raise CatalogError("生成 CODE V 安装包时需指定 CODE V 安装目录")
    if install_codev and codev_root is None:
        raise CatalogError("一键安装需指定 CODE V 安装目录")
    if not glasses:
        raise CatalogError("没有符合条件的材料，未写出文件")
    if str(output).casefold() in {g.source.casefold() for g in glasses}:
        raise CatalogError("输出路径与源库相同，请另存为新库")
    catalog_name = catalog_name or output.stem
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", catalog_name):
        raise CatalogError("新库名称须以英文字母开头，仅包含字母、数字或下划线")
    corrections = []
    if cap_transmission_at_one and target != "xml":
        raise CatalogError("透过率按 100% 导出的选项用于 AGF → CODE V XML；导出 AGF 时请取消此选项")
    if target == "xml" and (automatic_transmission or cap_transmission_at_one):
        prepared = []
        for glass in glasses:
            points = [point for point in glass.transmission_above_one
                      if cap_transmission_at_one or point["original_value"] <= AUTO_TRANSMISSION_LIMIT]
            if not points:
                prepared.append(glass)
                continue
            corrected = deepcopy(glass)
            corrected.transmission.extend((point["wavelength_um"], 1.0, point["thickness_mm"])
                                          for point in points)
            handled = {point["issue"] for point in points}
            corrected.issues = [issue for issue in corrected.issues if issue not in handled]
            corrected.transmission_above_one = [point for point in corrected.transmission_above_one if point["issue"] not in handled]
            prepared.append(corrected)
            for point in points:
                corrections.append({"source": glass.source, "catalog": glass.catalog, "glass": glass.name,
                                    **{key: value for key, value in point.items() if key != "issue"},
                                    "exported_value": 1.0,
                                    "policy": "cap_at_one" if cap_transmission_at_one else "automatic_cap_at_one"})
        glasses = prepared
    _check_cross_format(glasses, target)
    warnings = []
    if corrections:
        warnings.append(f"按所选策略将 {len(corrections)} 个超过 100% 的 AGF 内透过率值按 100% 写入 XML；"
                        "原始 AGF 保留，逐点原值和导出值见报告 transmission_corrections。")
    if transmission_thickness is not None and (not math.isfinite(transmission_thickness) or transmission_thickness <= 0):
        raise CatalogError("透过率厚度必须为正数，单位 mm")
    names = []
    used = {}
    for glass in glasses:
        name = f"{glass.catalog}_{glass.name}" if prefix_source else glass.name
        if target == "xml":
            name = _codev_name(name)
        elif re.fullmatch(r"\d{6}", name):
            raise CatalogError(f"{name} 是六位纯数字，会被 Zemax 当作 MIL 模型；请用 --prefix-source 添加来源前缀")
        if not name or any(c.isspace() for c in name):
            raise CatalogError(f"玻璃名称无效：{name!r}")
        if name.casefold() in used:
            raise CatalogError(f"导出名称冲突：{used[name.casefold()]} 与 {glass.catalog}/{glass.name} → {name}；可用 --prefix-source 添加来源前缀")
        used[name.casefold()] = f"{glass.catalog}/{glass.name}"
        names.append(name)
    cross = [g for g in glasses if g.format != target]
    for g in glasses:
        warnings.extend(f"{g.catalog}/{g.name}: {issue}" for issue in g.issues)
    if cross:
        if target == "xml":
            warnings += ["AGF 的 GC、MIL、Exclude Sub、melt frequency、dPgF、Ignore Thermal Exp、MD、OD、BD 及未知记录保留在源文件，未映射到 XML。",
                         "XML 的色散温度沿用旧程序 20°C；TD 参考温度单独保存在热光常数中。需在软件内核对非 20°C 数据。",
                         "仅写入原始热光常数，不生成未经核对的 dn/dT 温区表。价格 0 和日期是导出占位值。"]
        else:
            warnings += ["CODE V 的价格、日期、替代材料、厂家扩展属性和 catalog 元数据不能完整写入 AGF；原 XML 保留这些信息。",
                         "CODE V 供应状态按含义近似映射到 AGF；无直接对应的状态归为 Special。ED 缺项以 0 占位。",
                         "CTE 转换保留系数值；CODE V 原始温区可能与 AGF 的 -30–70 / 100–300°C 不同，温区不等价时需复核。"]
    if target == "xml":
        native_roots = {g.source: g.native_root for g in glasses if g.native_root is not None}
        if len(native_roots) == 1 and not cross:
            root = deepcopy(next(iter(native_roots.values())))
            root.find("Name").text = catalog_name
            full = root.find("Fullname")
            if full is not None:
                full.text = catalog_name
            container = root.find("Glasses")
            container.clear()
        else:
            root = ET.Element("Catalog")
            for tag, value in (("Name", catalog_name), ("Fullname", catalog_name), ("Version", "3")):
                _sub(root, tag, value)
            _merge_xml_metadata(root, glasses)
            container = ET.SubElement(root, "Glasses")
        for glass, name in zip(glasses, names):
            container.append(_make_glass_xml(glass, name))
        ET.indent(root, space="   ")
        data = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    else:
        records = [f"CC {catalog_name} - glass_catalog.py export"]
        seen_sources = set()
        for glass in glasses:
            if glass.source not in seen_sources:
                records.extend(glass.agf_header)
                seen_sources.add(glass.source)
        for glass, name in zip(glasses, names):
            if transmission_thickness is not None and glass.format == "xml":
                matching = [p for p in glass.transmission if math.isclose(p[2], transmission_thickness, rel_tol=1e-9, abs_tol=1e-9)]
                if glass.transmission and not matching:
                    raise CatalogError(f"{glass.name} 没有 {transmission_thickness} mm 透过率数据")
                selected_glass = deepcopy(glass)
                selected_glass.transmission = matching
                warnings.append(f"{glass.catalog}/{glass.name}：仅导出 {transmission_thickness} mm 透过率曲线。")
            else:
                selected_glass = glass
            records.extend(_agf_record(selected_glass, name))
        data = ("\n".join(records).rstrip() + "\n").encode("utf-16")
    report = {"ok": True, "output": str(output), "catalog": catalog_name, "count": len(glasses),
              "format": target, "warnings": list(dict.fromkeys(warnings)),
              "name_map": [{"source": g.source, "catalog": g.catalog, "original": g.name, "exported": n}
                           for g, n in zip(glasses, names)],
              "output_sha256": hashlib.sha256(data).hexdigest(),
              "selection": selection_info or {}, "transmission_thickness_mm": transmission_thickness,
              "transmission_corrections": corrections,
              "transmission_policy": {"automatic": automatic_transmission, "automatic_upper_limit": AUTO_TRANSMISSION_LIMIT,
                                      "explicit_cap_all": cap_transmission_at_one}}
    if any(g.supplier_reference for g in glasses):
        from supplier_catalog import reference_report
        report["supplier_data"] = reference_report(glasses)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(data)
    if codev_root is not None:
        from codev_catalog_bundle import prepare
        try:
            package = prepare(output, codev_root, bundle_dir)
        except (OSError, ValueError, ET.ParseError) as exc:
            report["ok"] = False
            report["codev_bundle_error"] = str(exc)
        else:
            report["codev_bundle"] = package["bundle"]
            report["codev_manifest"] = str(Path(package["bundle"]) / "manifest.json")
    if install_codev and "codev_bundle" in report:
        from codev_catalog_bundle import apply
        try:
            installation = apply(report["codev_bundle"])
            report["codev_installation"] = installation
            if not installation["ok"]:
                report["ok"] = False
                report["codev_install_error"] = "安装后的文件核对未通过"
        except (OSError, ValueError, KeyError, ET.ParseError) as exc:
            report["ok"] = False
            report["codev_install_error"] = str(exc)
    if write_report:
        report_path = output.with_suffix(output.suffix + ".report.json")
        report["report"] = str(report_path)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        if "codev_bundle" in report:
            (Path(report["codev_bundle"]) / "conversion-report.json").write_bytes(report_path.read_bytes())
    if "codev_bundle_error" in report:
        raise CatalogError(f"XML 已生成：{output}；CODE V 材料和热光目录尚未生成：{report['codev_bundle_error']}；"
                           f"转换记录：{report.get('report', '未要求保存报告')}")
    if "codev_install_error" in report:
        raise CatalogError(f"文件已导出，CODE V 安装未完成：{report['codev_install_error']}；"
                           f"导出目录：{report['codev_bundle']}；转换记录：{report.get('report', '未要求保存报告')}")
    return report


def build_parser():
    parser = argparse.ArgumentParser(description="Zemax / CODE V 玻璃库转换、筛选、安装管理与 Glass Expert DAT")
    sub = parser.add_subparsers(dest="command", required=True)
    for command, help_text in (("inspect", "查看材料，支持筛选及 JSON"), ("convert", "筛选、组合并另存为 AGF / XML / Glass Expert DAT")):
        p = sub.add_parser(command, help=help_text)
        p.add_argument("inputs", nargs="+", type=Path)
        p.add_argument("--json", action="store_true", help="输出机器可读 JSON，失败时 exit 2")
        p.add_argument("--name", default="", help="材料名称包含的文字，不区分大小写")
        p.add_argument("--names", nargs="+", help="精确材料名称白名单")
        p.add_argument("--source-catalog", dest="catalog", help="来源库名称")
        p.add_argument("--convertible-only", action="store_true", help="仅选已支持模型且光学记录有效的材料；不支持材料明确排除")
        for metric in ("nd", "vd", "density"):
            for bound in ("min", "max"):
                p.add_argument(f"--{metric}-{bound}", type=float)
        p.add_argument("--status", type=int, nargs="+", choices=range(5), help="兼容旧 AGF 状态筛选；XML 使用近似映射，精确筛选请用 --supply-status")
        p.add_argument("--supply-status", nargs="+", choices=tuple(SUPPLY_STATUS_LABELS),
                       help="原生供应状态，多选为 OR，例如 agf:0 agf:1 或 codev:10 codev:11；数字按各自软件定义")
        p.add_argument("--melt-frequency", type=int, nargs="+", choices=range(1, 6),
                       help="Zemax NM 独立的熔炼频率等级，例如 1 2 3；1 很频繁、5 很少，不自动等同厂家 MA/A/B/C/D")
        p.add_argument("--supplier-table", type=Path, help="可选厂家 CSV/TSV/XLSX；按厂家和牌号匹配，不改光学记录")
        p.add_argument("--supplier", help="厂家库名前缀，例如 CDGM；已知厂家可从表文件名自动识别")
        p.add_argument("--supplier-grade", nargs="+", choices=("MA", "A", "B", "C", "D"), help="按已载入厂家表中的原始分级多选，例如 MA A B")
        p.add_argument("--it-at-nm", dest="transmission_wavelength_nm", type=float, help="内透过率筛选波长，nm；不外推")
        p.add_argument("--it-thickness-mm", dest="transmission_thickness_mm", type=float, help="内透过率筛选厚度，mm；按指数规律换算")
        p.add_argument("--it-min", dest="transmission_min_percent", type=float, help="内透过率下限，百分数，例如 95")
        p.add_argument("--it-max", dest="transmission_max_percent", type=float, help="内透过率上限，百分数")
        if command == "convert":
            p.add_argument("--output", "-o", type=Path, required=True)
            p.add_argument("--catalog-name", help="新库名，默认取输出文件名")
            p.add_argument("--prefix-source", action="store_true", help="给玻璃名加来源库前缀，解决跨库同名")
            p.add_argument("--transmission-thickness", type=float, help="XML → AGF 时选择透过率厚度，mm")
            p.add_argument("--cap-transmission-at-one", action="store_true",
                           help="明确将全部超出 100% 的 AGF 内透过率按 100% 导出 XML；默认仅自动处理不超过 100.1% 的轻微超限")
            p.add_argument("--strict-transmission", action="store_true", help="关闭轻微透过率超限的自动处理")
            p.add_argument("--codev-root", type=Path, help="CODE V 安装目录；XML 生成两张目录合并包，DAT 必填并核对已安装库")
            p.add_argument("--bundle", type=Path, help="CODE V 配套目录输出位置；默认在 XML 旁新建带时间的目录")
            p.add_argument("--install-codev", action="store_true", help="一键转换、备份并安装到 --codev-root 指定的 CODE V")
            p.add_argument("--expert-reference", choices=("auto", "source"), default="source",
                           help="DAT 仅引用 --codev-root 下已安装的 XML 库；auto 为 source 的兼容别名")
    return parser


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in {"codev", "zemax", "gui"}:
        command = argv.pop(0)
        if command == "codev":
            from codev_catalog_bundle import main as run
        elif command == "zemax":
            from zemax_catalog_manager import main as run
        else:
            from glass_catalog_gui import main as run
            return run()
        return run(argv)
    args = build_parser().parse_args(argv)
    try:
        catalogs = [load_catalog(p) for p in args.inputs]
        all_glasses = [g for c in catalogs for g in c.glasses]
        supplier_info = None
        if args.supplier_table:
            from supplier_catalog import enrich_glasses, load_supplier_table
            table = load_supplier_table(args.supplier_table, args.supplier)
            all_glasses = enrich_glasses(all_glasses, table)
            supplier_info = {**table.summary(), "matched": sum(g.supplier_grade is not None for g in all_glasses),
                             "input_count": len(all_glasses)}
        elif args.supplier or args.supplier_grade:
            raise CatalogError("按厂家分级筛选需先用 --supplier-table 指定厂家表")
        keys = ("name", "names", "catalog", "nd_min", "nd_max", "vd_min", "vd_max", "density_min", "density_max", "status", "supply_status", "melt_frequency", "supplier_grade", "convertible_only",
                "transmission_wavelength_nm", "transmission_thickness_mm", "transmission_min_percent", "transmission_max_percent")
        filters = {key: getattr(args, key) for key in keys}
        selected = select_glasses(all_glasses, **filters)
        if args.command == "inspect":
            result = {"ok": True, "total": len(all_glasses), "selected": len(selected),
                      "catalogs": [{"name": c.name, "source": c.source, "format": c.format,
                                    "encoding": c.encoding, "count": len(c.glasses)} for c in catalogs],
                      "glasses": [g.summary() for g in selected]}
            if supplier_info:
                result["supplier_table"] = supplier_info
            if args.transmission_wavelength_nm is not None:
                for glass, item in zip(selected, result["glasses"]):
                    value = transmission_at(glass, args.transmission_wavelength_nm, args.transmission_thickness_mm)
                    item["filter_internal_transmission_percent"] = None if value is None else value * 100
                result["transmission_query"] = {"wavelength_nm": args.transmission_wavelength_nm,
                                                "thickness_mm": args.transmission_thickness_mm,
                                                "method": "linear_wavelength_interpolation_then_beer_lambert_no_extrapolation"}
        else:
            result = export_catalog(selected, args.output, catalog_name=args.catalog_name,
                                    prefix_source=args.prefix_source, transmission_thickness=args.transmission_thickness,
                                    cap_transmission_at_one=args.cap_transmission_at_one,
                                    automatic_transmission=not args.strict_transmission,
                                    codev_root=args.codev_root, bundle_dir=args.bundle,
                                    install_codev=args.install_codev,
                                    expert_reference=args.expert_reference,
                                    selection_info={"input_count": len(all_glasses), "filters": filters,
                                                    **({"supplier_table": supplier_info} if supplier_info else {})})
        if args.json:
            print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        elif args.command == "inspect":
            print(f"共 {len(all_glasses)} 种材料，筛选后 {len(selected)} 种")
            print("来源库\t材料\tnd\tVd\t密度\t色散公式")
            for glass in selected:
                print("\t".join(str(x) if x is not None else "—" for x in
                                (glass.catalog, glass.name, glass.nd, glass.vd, glass.density, glass.equation)))
        else:
            print(f"已导出 {result['count']} 种材料：{result['output']}")
            for warning in result["warnings"]:
                print(f"说明：{warning}")
            print(f"转换报告：{result['report']}")
            if "codev_bundle" in result:
                installed = result.get("codev_installation")
                print(f"CODE V 材料和热光目录：{result['codev_bundle']}（{'已安装并核对文件' if installed else '尚未安装'}）")
                if installed:
                    print(f"备份：{installed['backup']}；CODE V 内识别待验证。")
        return 0
    except (OSError, ValueError, ET.ParseError) as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        else:
            print(f"错误：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
