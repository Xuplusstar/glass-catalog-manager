"""Synthetic records and macro headers; no vendor catalog is redistributed."""

from pathlib import Path


SYNTHETIC_AGF = """CC Synthetic mapping fixtures, not manufacturer material data
NM SYNTH_A 1 655610 1.65 61 0 1 2
ED 9.7 12.2 2.8 0.001 0
CD 2.7225 0 .008 0 0 0
LD .3 2.5
IT .5 .95 5
IT .6 .98 5
NM SYNTH_B 2 0 1.5168 64.17 0 0 1
ED 7.1 8.3 2.51 0 0
CD 1.03961212 .00600069867 .231792344 .0200179144 1.01046945 103.560653
LD .29 2.5
IT .5 .99 5
IT .6 .995 5
"""

FULL_HEADERS = "Catalog Glass Index V-value NF-NC DPF Price Avail Bubble Stain".split() + [
    "Low WL", "High WL", *"Price_gob Specific_grav Manufacture_date date_received date_index_changed Equation_type Replacement Low_exp_coeff High_exp_coeff Transform_temp Knoop Poisson Young Acid_resist Acid_resist_powder Acid_resist_surface Rigidity Water_resist".split()]
THERMAL_HEADERS = "Glass Catalog Formula A1/B1 A2/C1 A3/B2 A4/C2 A5/B3 A6/C3 D0 D1 D2 E0 E1 lambda MeasuredTemp Alpha_lowT Tmin_al Tmax_al Alpha_highT Tmin_ah Tmax_ah".split()


def write_catalog(path):
    path = Path(path)
    path.write_text(SYNTHETIC_AGF, encoding="utf-8")
    return path


def write_codev_tables(root):
    macro = Path(root) / "macro"
    macro.mkdir(parents=True, exist_ok=True)
    full_row = {"Catalog": "BASE", "Glass": "REFERENCE", "Index": "1.5", "V-value": "50", "Avail": "1", "Equation_type": "SCHT"}
    thermal_row = {"Catalog": "BASE", "Glass": "REFERENCE", "Formula": "lau"}
    contents = {}
    for name, prefix, headers, row in (("CatalogFull.dat", "", FULL_HEADERS, full_row),
                                      ("dndt_constants.dat", "Version#3\r\n", THERMAL_HEADERS, thermal_row)):
        data = (prefix + "\t".join(headers) + "\r\n" + "\t".join(row.get(key, "--") for key in headers) + "\r\n").encode("utf-8")
        (macro / name).write_bytes(data)
        contents[name] = data
    return contents
