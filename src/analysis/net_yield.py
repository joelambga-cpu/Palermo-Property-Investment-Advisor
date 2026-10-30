"""
Net yield model: short-term (Airbnb) vs long-term rental, Palermo.

Simple-language summary
-----------------------
For each active Airbnb listing we ask: "if an investor bought a flat like
this one, paid all costs and taxes, how much would be left each year?"
We compare that with renting the same flat long-term at OMI rent values.

v1 runs at CITY level (median OMI price and rent across the 49 zones).
When the OMI zone perimeters arrive, the same functions run per zone:
only `price_m2` and `rent_m2_month` change.

All parameters live in config/assumptions.csv.
Revenue data (Inside Airbnb, 25 Sep 2026) predates Airbnb's 15.5% host-only
fee (13 Oct 2026): we apply the new fee to historical revenue, i.e. we
assume hosts did NOT raise prices to compensate.
"""

from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parents[2]
ASSUMPTIONS_FILE = BASE_DIR / "config" / "assumptions.csv"
AIRBNB_FILE = BASE_DIR / "data" / "processed" / "airbnb_palermo_clean.csv"
OMI_FILE = BASE_DIR / "data" / "raw" / "omi_legacy" / "palermo_omi_2025S2_49_zone.csv"
OUTPUT_DIR = BASE_DIR / "data" / "processed"

# Unit size by bedrooms (assumption, declared)
SIZE_M2_BY_BEDROOMS = {1: 60, 2: 85, 3: 120}


def load_assumptions() -> dict:
    a = pd.read_csv(ASSUMPTIONS_FILE)
    a = a[pd.to_numeric(a["value"], errors="coerce").notna()]
    return dict(zip(a["parameter"], a["value"].astype(float)))


# ---------------------------------------------------------------- costs
def property_costs(size_m2: float, price_m2: float, p: dict) -> dict:
    """Purchase price, one-off acquisition costs and yearly owner costs."""
    price = size_m2 * price_m2
    rendita = p["rendita_catastale_per_m2"] * size_m2

    registro = max(1000, p["registro_rate"] * rendita * p["valore_catastale_multiplier"])
    agency = p["agency_fee_rate"] * 1.22 * price  # + VAT 22%
    acquisition = registro + p["fixed_purchase_taxes"] + p["notary_fee"] + agency

    return {
        "price": price,
        "acquisition_costs": acquisition,
        "imu": rendita * p["imu_base_multiplier"] * p["imu_rate"],
        "maintenance": p["maintenance_rate"] * price,
        "insurance": p["insurance"],
        "condominio": p["condominio_owner"],
    }


def long_term_net(size_m2: float, price_m2: float, rent_m2_month: float, p: dict) -> dict:
    c = property_costs(size_m2, price_m2, p)
    gross = rent_m2_month * size_m2 * 12 * (1 - p["vacancy_ltr"])
    tax = gross * p["cedolare_ltr"]
    costs = (
        c["imu"] + c["maintenance"] + c["insurance"]
        + c["condominio"] * p["condominio_ltr_owner_share"]
        + p["utilities_ltr"]
    )
    invested = c["price"] + c["acquisition_costs"]
    net = gross - tax - costs
    return {"gross": gross, "net": net, "invested": invested, "net_yield": net / invested}


def short_term_net(revenue, nights, size_m2, price_m2, p, tax_rate):
    """Works on scalars or pandas Series (one row per listing)."""
    c = property_costs(size_m2, price_m2, p)
    stays = nights / p["avg_length_of_stay"]
    variable = (
        revenue * p["airbnb_host_fee"]
        + stays * p["cleaning_cost_per_stay"]
        + nights * p["consumables_per_night"]
    )
    fixed = (
        p["utilities_str"] + c["condominio"] + c["imu"]
        + c["maintenance"] + c["insurance"]
    )
    tax = revenue * tax_rate  # cedolare on gross rent, fees not deductible
    invested = c["price"] + c["acquisition_costs"] + p["furnishing_str"] + p["cin_safety_setup"]
    net = revenue - variable - fixed - tax
    return net, invested


# ------------------------------------------------------------ analysis
def city_inputs() -> tuple[float, float]:
    omi = pd.read_csv(OMI_FILE, encoding="utf-8-sig")
    price_m2 = ((omi["prezzo_min_mq"] + omi["prezzo_max_mq"]) / 2).median()
    rent_m2 = omi["affitto_medio_mq_mese"].median()
    return price_m2, rent_m2


def listing_level(p: dict, price_m2: float, rent_m2: float, tax_rate: float) -> pd.DataFrame:
    df = pd.read_csv(AIRBNB_FILE)
    df = df[(df["in_scope"] == 1) & (df["bedrooms"].isin(SIZE_M2_BY_BEDROOMS))].copy()
    df["bedrooms"] = df["bedrooms"].astype(int)
    df["size_m2"] = df["bedrooms"].map(SIZE_M2_BY_BEDROOMS)

    parts = []
    for size, g in df.groupby("size_m2"):
        g = g.copy()
        net, invested = short_term_net(
            g["estimated_revenue_l365d"], g["estimated_occupancy_l365d"],
            size, price_m2, p, tax_rate,
        )
        ltr = long_term_net(size, price_m2, rent_m2, p)
        g["str_net"] = net
        g["str_yield"] = net / invested
        g["ltr_net"] = ltr["net"]
        g["ltr_yield"] = ltr["net_yield"]
        g["str_beats_ltr"] = (g["str_yield"] > g["ltr_yield"]).astype(int)
        parts.append(g)
    return pd.concat(parts)


def break_even_nights(adr, size_m2, price_m2, rent_m2, p, tax_rate) -> float:
    """Nights/year at which short-term yield equals long-term yield."""
    ltr = long_term_net(size_m2, price_m2, rent_m2, p)
    _, invested = short_term_net(0, 0, size_m2, price_m2, p, tax_rate)
    fixed = -short_term_net(0, 0, size_m2, price_m2, p, tax_rate)[0]
    target_net = ltr["net_yield"] * invested
    margin_per_night = (
        adr * (1 - p["airbnb_host_fee"] - tax_rate)
        - p["cleaning_cost_per_stay"] / p["avg_length_of_stay"]
        - p["consumables_per_night"]
    )
    return (target_net + fixed) / margin_per_night


def summary(df: pd.DataFrame) -> pd.DataFrame:
    return (
        df.groupby("bedrooms")
        .agg(
            listings=("listing_id", "size"),
            size_m2=("size_m2", "first"),
            adr_median=("price_eur", "median"),
            nights_median=("estimated_occupancy_l365d", "median"),
            str_net_p25=("str_net", lambda s: s.quantile(0.25)),
            str_net_median=("str_net", "median"),
            str_net_p75=("str_net", lambda s: s.quantile(0.75)),
            ltr_net=("ltr_net", "first"),
            ltr_yield_pct=("ltr_yield", lambda s: s.iloc[0] * 100),
            str_yield_median_pct=("str_yield", lambda s: s.median() * 100),
            pct_str_beats_ltr=("str_beats_ltr", lambda s: s.mean() * 100),
        )
        .round(1)
    )


def scenario_a_vs_b(df: pd.DataFrame, p: dict, price_m2: float, rent_m2: float) -> pd.DataFrame:
    """A = 1 unit x 3 bedrooms (120 m2); B = 2 units x 1 bedroom (60 m2), 21% + 26%."""
    rows = []
    one = df[df["bedrooms"] == 1]
    three = df[df["bedrooms"] == 3]
    for q in (0.25, 0.5, 0.75):
        # A: one large unit at the q-th percentile of 3-bedroom listings
        rev, n = three["estimated_revenue_l365d"].quantile(q), three["estimated_occupancy_l365d"].quantile(q)
        a_net, a_inv = short_term_net(rev, n, 120, price_m2, p, p["cedolare_str_first_unit"])
        # B: two small units at the q-th percentile of 1-bedroom listings
        rev1, n1 = one["estimated_revenue_l365d"].quantile(q), one["estimated_occupancy_l365d"].quantile(q)
        b1, inv1 = short_term_net(rev1, n1, 60, price_m2, p, p["cedolare_str_first_unit"])
        b2, _ = short_term_net(rev1, n1, 60, price_m2, p, p["cedolare_str_second_unit"])
        rows.append({
            "percentile": f"P{int(q*100)}",
            "A_1x120m2_net": a_net, "A_invested": a_inv, "A_yield_pct": a_net / a_inv * 100,
            "B_2x60m2_net": b1 + b2, "B_invested": 2 * inv1, "B_yield_pct": (b1 + b2) / (2 * inv1) * 100,
        })
    ltr_a = long_term_net(120, price_m2, rent_m2, p)
    ltr_b = long_term_net(60, price_m2, rent_m2, p)
    rows.append({
        "percentile": "Long-term",
        "A_1x120m2_net": ltr_a["net"], "A_invested": ltr_a["invested"], "A_yield_pct": ltr_a["net_yield"] * 100,
        "B_2x60m2_net": 2 * ltr_b["net"], "B_invested": 2 * ltr_b["invested"], "B_yield_pct": ltr_b["net_yield"] * 100,
    })
    return pd.DataFrame(rows).round(1)


if __name__ == "__main__":
    pd.set_option("display.width", 200)
    p = load_assumptions()
    price_m2, rent_m2 = city_inputs()
    tax = p["cedolare_str_first_unit"]
    print(f"Input città (mediana 49 zone OMI): {price_m2:.0f} €/m², affitto {rent_m2:.1f} €/m²/mese\n")

    listings = listing_level(p, price_m2, rent_m2, tax)
    s = summary(listings)
    print("1) Netto annuo per taglio — breve (percentili annunci attivi) vs lungo:")
    print(s.to_string(), "\n")

    print("2) Break-even: notti/anno perché il breve renda quanto il lungo")
    for b, size in SIZE_M2_BY_BEDROOMS.items():
        adr = s.loc[b, "adr_median"]
        n = break_even_nights(adr, size, price_m2, rent_m2, p, tax)
        print(f"   {b} camera/e ({size} m², {adr:.0f} €/notte): {n:.0f} notti "
              f"(mediana attuale {s.loc[b, 'nights_median']:.0f})")

    print("\n3) Scenario A (1 x 120 m²) vs B (2 x 60 m²):")
    ab = scenario_a_vs_b(listings, p, price_m2, rent_m2)
    print(ab.to_string(index=False))

    s.to_csv(OUTPUT_DIR / "net_yield_city_by_bedrooms.csv")
    ab.to_csv(OUTPUT_DIR / "scenario_a_vs_b_city.csv", index=False)
