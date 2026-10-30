"""
Load Inside Airbnb listings (Sicily snapshot) for the Comune di Palermo,
clean the fields needed for the revenue module and store them in SQLite.

Input : data/raw/airbnb/listings.csv.gz
Output: data/processed/airbnb_palermo_clean.csv
        table `airbnb_listings` in data/database/real_estate.db

Assumptions (declared in docs/data_sources.md):
- Prices are in EUR. Inside Airbnb prints a "$" sign for every city,
  but values are in the local currency.
- Occupancy and revenue are Inside Airbnb's own estimates
  (review-based model, capped at 255 nights/year).
- Listing coordinates are anonymised (offset up to ~150 m).
"""

from pathlib import Path
import sqlite3

import pandas as pd

BASE_DIR = Path(__file__).resolve().parents[2]

RAW_FILE = BASE_DIR / "data" / "raw" / "airbnb" / "listings.csv.gz"
PROCESSED_FILE = BASE_DIR / "data" / "processed" / "airbnb_palermo_clean.csv"
DB_FILE = BASE_DIR / "data" / "database" / "real_estate.db"
SQL_FILE = BASE_DIR / "sql" / "airbnb_summary.sql"

COMUNE = "Palermo"
MAX_NIGHTS_SHORT_TERM = 30  # oltre 30 notti non è affitto breve

COLUMNS = [
    "id",
    "last_scraped",
    "host_id",
    "host_is_superhost",
    "calculated_host_listings_count",
    "neighbourhood_cleansed",
    "latitude",
    "longitude",
    "property_type",
    "room_type",
    "accommodates",
    "bedrooms",
    "beds",
    "bathrooms",
    "price",
    "minimum_nights",
    "availability_365",
    "number_of_reviews",
    "number_of_reviews_ltm",
    "last_review",
    "review_scores_rating",
    "estimated_occupancy_l365d",
    "estimated_revenue_l365d",
    "license",
]


def load_listings() -> pd.DataFrame:
    df = pd.read_csv(RAW_FILE, usecols=COLUMNS, low_memory=False)
    print(f"Annunci Sicilia: {len(df):,}")

    df = df[df["neighbourhood_cleansed"] == COMUNE].copy()
    print(f"Annunci {COMUNE}: {len(df):,}")
    return df


def clean(df: pd.DataFrame) -> pd.DataFrame:
    df = df.rename(columns={"id": "listing_id"})

    # "$1,234.50" -> 1234.50 (valori in EUR, vedi docstring)
    df["price_eur"] = pd.to_numeric(
        df["price"].str.replace(r"[^\d.]", "", regex=True),
        errors="coerce",
    )
    df = df.drop(columns=["price"])

    df["host_is_superhost"] = df["host_is_superhost"].map({"t": 1, "f": 0})
    df["has_cin"] = df["license"].notna().astype(int)

    # Flag di perimetro: non si cancella niente, si marca
    df["is_entire_home"] = (df["room_type"] == "Entire home/apt").astype(int)
    df["is_active"] = (df["number_of_reviews_ltm"] > 0).astype(int)
    df["is_short_term"] = (
        df["minimum_nights"] <= MAX_NIGHTS_SHORT_TERM
    ).astype(int)
    df["is_multi_host"] = (df["calculated_host_listings_count"] >= 3).astype(int)

    # Outlier di prezzo: fuori dal 1°–99° percentile delle case intere
    entire_prices = df.loc[df["is_entire_home"] == 1, "price_eur"]
    low, high = entire_prices.quantile([0.01, 0.99])
    df["is_price_outlier"] = (
        df["price_eur"].notna()
        & ((df["price_eur"] < low) | (df["price_eur"] > high))
    ).astype(int)

    df["in_scope"] = (
        (df["is_entire_home"] == 1)
        & (df["is_active"] == 1)
        & (df["is_short_term"] == 1)
        & (df["price_eur"].notna())
        & (df["is_price_outlier"] == 0)
    ).astype(int)

    # Placeholder: assegnata nel Ponte con i perimetri OMI
    df["codice_zona"] = None

    print(f"Soglie outlier prezzo (P1–P99): {low:.0f} € – {high:.0f} €")
    return df


def quality_checks(df: pd.DataFrame) -> None:
    print("\nControlli qualità:")
    print("ID duplicati:", df["listing_id"].duplicated().sum())
    print("Prezzi mancanti:", df["price_eur"].isna().sum())
    print("Coordinate mancanti:", df[["latitude", "longitude"]].isna().any(axis=1).sum())
    print(
        "Occupazione fuori range (0–365):",
        (~df["estimated_occupancy_l365d"].between(0, 365)).sum(),
    )

    print("\nImbuto perimetro analisi:")
    steps = [
        ("Tutti gli annunci", pd.Series(True, index=df.index)),
        ("Casa intera", df["is_entire_home"] == 1),
        ("+ attivi (recensione ultimi 12 mesi)", (df["is_entire_home"] == 1) & (df["is_active"] == 1)),
        ("+ soggiorno minimo ≤ 30 notti", (df["is_entire_home"] == 1) & (df["is_active"] == 1) & (df["is_short_term"] == 1)),
        ("+ prezzo valido, no outlier (= in_scope)", df["in_scope"] == 1),
    ]
    for label, mask in steps:
        print(f"  {label:<45} {mask.sum():>6,}")


def save(df: pd.DataFrame) -> None:
    PROCESSED_FILE.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(PROCESSED_FILE, index=False)
    print(f"\nCSV salvato: {PROCESSED_FILE}")

    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_FILE) as conn:
        df.to_sql("airbnb_listings", conn, if_exists="replace", index=False)
        print(f"Tabella airbnb_listings caricata: {len(df):,} righe")

        if SQL_FILE.exists():
            summary = pd.read_sql_query(SQL_FILE.read_text(encoding="utf-8"), conn)
            print("\nRiepilogo annunci in perimetro per numero di camere:")
            print(summary.to_string(index=False))


if __name__ == "__main__":
    listings = clean(load_listings())
    quality_checks(listings)
    save(listings)
