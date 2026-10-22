# Synthetic test fixtures

Every file in this folder is **artificial** and was written by hand to exercise specific
behaviours. None of it is real factory data, a measurement, or an industry benchmark.

| File | Purpose |
| --- | --- |
| `synthetic_resources.csv` | Valid resource records (Jan/Feb: 1,200 and 900 kWh; 3,000 and 2,400 L). |
| `synthetic_production.csv` | Valid production records (600 kg in each of Jan and Feb). |
| `invalid_import.csv` | Deliberately broken rows: bad date, bad quantity, unknown unit, unknown category, negative value, meter reading. |

Expected results for Jan + Feb (calculation specification, section 16): electricity 2 and
1.5 kWh/kg (overall 1.75), water 5 and 4 L/kg (overall 4.5).
