# International Cost of Capital Explorer

A Streamlit starter app for comparing a project's cost of equity, pre-tax cost of debt, and WACC in USD and a selected country's local currency.

## Files
- `app.py` — Streamlit application
- `requirements.txt` — Python dependencies

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate        # macOS/Linux
# .venv\\Scripts\\activate     # Windows
pip install -r requirements.txt
streamlit run app.py
```

## Deploy on Streamlit Community Cloud
1. Create a GitHub repository.
2. Upload `app.py`, `requirements.txt`, and `README.md` to the repository root.
3. In Streamlit Community Cloud, create an app from that repository and select `app.py` as the entry point.

## Data sources
- Damodaran US industry unlevered betas: https://pages.stern.nyu.edu/~adamodar/pc/datasets/betas.xls
- Damodaran ratings and default spreads (Baa2/BBB, large non-financial service firms): https://pages.stern.nyu.edu/adamodar/New_Home_Page/datafile/ratings.html
- OECD statutory corporate income tax rates (assignment source): https://www.oecd.org/en/publications/corporate-tax-statistics-2024_9c27d6e8-en/full-report/statutory-corporate-income-tax-rates_440f9286.html#chapter-d1e2342-08e74a33fb
- Trading Economics government bond yields: https://tradingeconomics.com/bonds

The app displays source links and retrieval timestamps. Source pages may change their layout or restrict automated access; manual overrides are included for all key inputs.

## Formulas currently implemented (confirm against the formulas supplied in class)
This starter uses conventional formulas:

- Relevered beta: `beta_L = beta_U * (1 + (1 - tax) * D/E)`
- Cost of equity: `Re = local 10-year government yield + beta_L * ERP`
- Pre-tax cost of debt: `Rd = local 10-year government yield + BBB spread`
- WACC: `WACC = E/V * Re + D/V * Rd * (1 - tax)`

The same project tax rate, equity risk premium, debt share, and unlevered beta are used in both currency calculations.

### Important provisional assumption: foreign BBB spread
The assignment says the foreign BBB spread should be automatically calculated but does not specify the formula in the prompt. This starter uses the transparent proxy:

`foreign BBB spread = USD BBB spread + (foreign 10-year yield - US 10-year yield)`

This is a placeholder assumption, not a confirmed class formula. Replace it with the instructor's formula once provided. The foreign spread can be manually overridden independently of the USD spread.

## Verification checks included
- Equal government yields and equal shared parameters produce equal results when the foreign spread override is off and the auto spread resolves to the USD spread.
- Zero debt makes WACC equal cost of equity.
- The foreign spread is used only in the foreign-currency calculation; changing it does not change USD results.

## Notes
- The default industry is Software (System & Application), if present in the downloaded Damodaran workbook.
- The default target country is United States.
- Default ERP is 6.5%; default debt share is 30%; default project tax selection is the US rate.
- This is an educational model, not investment advice.
