-- Annunci Airbnb Palermo in perimetro (casa intera, attivi, ≤30 notti, no outlier)
-- Mediane non disponibili in SQLite: si usano medie + conteggi; le mediane sono in Python.
SELECT
    CAST(bedrooms AS INTEGER)                    AS camere,
    COUNT(*)                                     AS annunci,
    ROUND(AVG(price_eur), 0)                     AS prezzo_medio_notte,
    ROUND(AVG(estimated_occupancy_l365d), 0)     AS notti_medie_anno,
    ROUND(AVG(estimated_revenue_l365d), 0)       AS ricavo_medio_anno,
    ROUND(100.0 * AVG(is_multi_host), 1)         AS pct_property_manager
FROM airbnb_listings
WHERE in_scope = 1
  AND bedrooms BETWEEN 1 AND 3
GROUP BY CAST(bedrooms AS INTEGER)
ORDER BY camere;
