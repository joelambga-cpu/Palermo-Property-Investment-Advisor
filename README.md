# Palermo Property Investment Advisor

> Work in progress — first complete version planned for December 2026.

**Client:** a private investor (€200–300k budget) or a property manager in Palermo.
**Decision:** which OMI zone to buy in, one large unit vs two smaller units, short-term vs long-term rental, and at what nightly rate.
**Output:** a zone-level recommendation with estimated net annual return in €, stated assumptions and sensitivity ranges.

## Modules
- **A – Cost:** purchase and long-term rent €/m² by OMI zone (Agenzia delle Entrate – OMI)
- **B – Revenue:** short-term rental prices, occupancy and revenue (Inside Airbnb, Sicily snapshot)
- **Bridge:** net return by zone, short-term vs long-term (flat tax, costs, vacancy, CIN)

Builds on [real-estate-market-intelligence-palermo](https://github.com/joelambga-cpu/real-estate-market-intelligence-palermo).

## Stack
Python (pandas, geopandas) · SQL / SQLite · Power BI · Git
