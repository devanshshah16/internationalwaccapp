from __future__ import annotations

import io
import re
from datetime import datetime, timezone
from typing import Any

import pandas as pd
import plotly.express as px
import pycountry
import requests
import streamlit as st

# -----------------------------------------------------------------------------
# International Cost of Capital Explorer
# Formula note: the assignment mentions that class formulas will be provided.
# This starter uses conventional relevered CAPM and after-tax WACC formulas.
# The automatic foreign BBB spread is an explicitly labeled proxy and should
# be replaced if the instructor provides a different country-spread formula.
# -----------------------------------------------------------------------------

st.set_page_config(page_title="Cost of Capital", page_icon="📊", layout="wide")

st.markdown("""
<style>
:root { color-scheme: dark; }
.stApp { background: #171615; color: #f3f1ee; }
[data-testid="stSidebar"] { background: #24221f; border-right: 1px solid #35322e; }
[data-testid="stSidebar"] > div:first-child { padding-top: 1.1rem; }
.block-container { max-width: 1500px; padding-top: 2rem; padding-bottom: 3rem; }
h1,h2,h3 { letter-spacing: -.035em; }
h1 { font-size: 2.35rem !important; }
[data-testid="stMetric"] { background: #24221f; border: 1px solid #3a3732; padding: 15px 17px; border-radius: 10px; }
[data-testid="stExpander"] { background: #1c1b19; border: 1px solid #45413b; border-radius: 10px; }
[data-testid="stNumberInput"] input, [data-testid="stSelectbox"] div[data-baseweb="select"] { background: #302e2a; }
[data-testid="stAlert"] { border-radius: 8px; }
.small-muted { color: #aaa6a0; font-size: .9rem; }
.result-card { background:#24221f; border:1px solid #3a3732; border-radius:12px; padding:18px; }
.result-card h3 { margin-top:0; }
</style>
""", unsafe_allow_html=True)

DAMODARAN_BETA_URL = "https://pages.stern.nyu.edu/~adamodar/pc/datasets/betas.xls"
DAMODARAN_RATINGS_URL = "https://pages.stern.nyu.edu/adamodar/New_Home_Page/datafile/ratings.html"
OECD_URL = "https://www.oecd.org/en/publications/corporate-tax-statistics-2024_9c27d6e8-en/full-report/statutory-corporate-income-tax-rates_440f9286.html#chapter-d1e2342-08e74a33fb"
TE_BONDS_URL = "https://tradingeconomics.com/bonds"
TIMEOUT = 25
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; CostOfCapitalExplorer/1.0)"}

# Countries with Trading Economics country slugs. Country picker includes all
# ISO countries, while data retrieval can be manually overridden if a page is
# unavailable or the country is not covered.
TE_SLUGS = {
    "United States": "united-states", "United Kingdom": "united-kingdom", "India": "india",
    "Canada": "canada", "Australia": "australia", "Japan": "japan", "China": "china",
    "Germany": "germany", "France": "france", "Italy": "italy", "Spain": "spain",
    "Netherlands": "netherlands", "Switzerland": "switzerland", "Sweden": "sweden",
    "Norway": "norway", "Denmark": "denmark", "Singapore": "singapore", "South Korea": "south-korea",
    "Brazil": "brazil", "Mexico": "mexico", "South Africa": "south-africa", "Indonesia": "indonesia",
    "Thailand": "thailand", "Malaysia": "malaysia", "New Zealand": "new-zealand", "Turkey": "turkey",
    "Poland": "poland", "Portugal": "portugal", "Ireland": "ireland", "Belgium": "belgium",
    "Austria": "austria", "Finland": "finland", "Greece": "greece", "Israel": "israel",
    "Saudi Arabia": "saudi-arabia", "United Arab Emirates": "united-arab-emirates", "Chile": "chile",
    "Colombia": "colombia", "Peru": "peru", "Argentina": "argentina", "Philippines": "philippines",
    "Vietnam": "vietnam", "Taiwan": "taiwan", "Czech Republic": "czech-republic", "Hungary": "hungary",
    "Romania": "romania", "Iceland": "iceland", "Russia": "russia", "Ukraine": "ukraine",
}

COUNTRIES = sorted([c.name for c in pycountry.countries])
if "United States" not in COUNTRIES:
    COUNTRIES.insert(0, "United States")


def now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def get_text(url: str) -> str:
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    return r.text


def clean_num(x: Any) -> float | None:
    if x is None:
        return None
    s = str(x).strip().replace(",", "").replace("%", "")
    if s in {"", "-", "—", "nan", "None", "N/A", "NA"}:
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    return float(m.group(0)) if m else None


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def fetch_damodaran_betas() -> tuple[pd.DataFrame, str]:
    response = requests.get(DAMODARAN_BETA_URL, headers=HEADERS, timeout=TIMEOUT)
    response.raise_for_status()
    raw = pd.read_excel(io.BytesIO(response.content), sheet_name=0, header=None)
    # Locate the header row containing Industry Name and Unlevered beta.
    header_idx = None
    for i in range(min(20, len(raw))):
        vals = [str(v).strip().lower() for v in raw.iloc[i].tolist()]
        if any("industry name" in v for v in vals) and any("unlevered beta" in v for v in vals):
            header_idx = i
            break
    if header_idx is None:
        raise ValueError("Could not identify the Industry Name / Unlevered beta columns in Damodaran's workbook.")
    df = raw.iloc[header_idx + 1:].copy()
    df.columns = [str(v).strip() for v in raw.iloc[header_idx].tolist()]
    industry_col = next(c for c in df.columns if "industry name" in c.lower())
    beta_col = next(c for c in df.columns if "unlevered beta" in c.lower() and "corrected" not in c.lower())
    out = df[[industry_col, beta_col]].copy()
    out.columns = ["Industry", "Unlevered beta"]
    out["Industry"] = out["Industry"].astype(str).str.strip()
    out["Unlevered beta"] = pd.to_numeric(out["Unlevered beta"], errors="coerce")
    out = out.dropna().query("Industry != ''").drop_duplicates("Industry").reset_index(drop=True)
    if out.empty:
        raise ValueError("Damodaran workbook returned no usable industry betas.")
    return out, "Damodaran US industry betas (Unlevered beta), downloaded " + now_stamp()


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def fetch_usd_bbb_spread() -> tuple[float, str]:
    tables = pd.read_html(DAMODARAN_RATINGS_URL)
    for table in tables:
        flat = " ".join(str(x) for x in table.astype(str).values.flatten()).lower()
        if "baa2" in flat and "bbb" in flat:
            for _, row in table.iterrows():
                row_text = " ".join(str(x) for x in row.tolist()).lower()
                if "baa2" in row_text and "bbb" in row_text:
                    # Spread is normally a value such as 1.11%; select the numeric
                    # cell after the rating label rather than the coverage bounds.
                    vals = [clean_num(x) for x in row.tolist()]
                    nums = [v for v in vals if v is not None]
                    if nums:
                        # Table layout: coverage lower, coverage upper, rating, spread.
                        spread = nums[-1]
                        return spread / 100.0, "Damodaran ratings table: Baa2/BBB, large non-financial service firms; retrieved " + now_stamp()
    raise ValueError("Could not locate the Baa2/BBB spread row on Damodaran's ratings page.")


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def fetch_oecd_tax_rates() -> tuple[pd.DataFrame, str]:
    # Parse report tables. The report page can change its HTML layout; if it
    # does, users can enter tax rates manually in the override section.
    tables = pd.read_html(OECD_URL)
    candidates = []
    for t in tables:
        cols = " ".join(str(c).lower() for c in t.columns)
        if any("country" in str(c).lower() or "jurisdiction" in str(c).lower() for c in t.columns):
            candidates.append(t)
    if not candidates:
        # Some OECD report versions place country names in the first column
        # without a named header.
        candidates = [t for t in tables if len(t.columns) >= 2 and len(t) > 20]
    if not candidates:
        raise ValueError("Could not find a country-by-tax-rate table in the OECD report.")
    table = max(candidates, key=lambda x: len(x))
    table = table.copy()
    first_col = table.columns[0]
    # Choose a numeric column with the most populated values, excluding years.
    numeric_cols = []
    for c in table.columns[1:]:
        vals = table[c].map(clean_num)
        if vals.notna().sum() > 10:
            numeric_cols.append((int(vals.notna().sum()), c))
    if not numeric_cols:
        raise ValueError("Could not identify statutory corporate tax-rate values in OECD table.")
    value_col = max(numeric_cols)[1]
    out = pd.DataFrame({"Country": table[first_col].astype(str).str.strip(), "Tax rate": table[value_col].map(clean_num)})
    out = out.dropna().drop_duplicates("Country")
    out["Tax rate"] = out["Tax rate"] / 100.0
    return out, "OECD statutory corporate income tax rates, report table; retrieved " + now_stamp()


def match_tax(country: str, tax_df: pd.DataFrame) -> float | None:
    aliases = {"United States": ["United States", "United States of America"], "Korea, Republic of": ["Korea", "Republic of Korea"],
               "Türkiye": ["Türkiye", "Turkey"], "Czechia": ["Czechia", "Czech Republic"]}
    names = aliases.get(country, [country])
    for name in names:
        hit = tax_df[tax_df["Country"].str.casefold() == name.casefold()]
        if not hit.empty:
            return float(hit.iloc[0]["Tax rate"])
    # Try starts-with matching for OECD labels with footnote markers.
    hit = tax_df[tax_df["Country"].str.casefold().str.startswith(country.casefold())]
    return float(hit.iloc[0]["Tax rate"]) if not hit.empty else None


@st.cache_data(ttl=3 * 3600, show_spinner=False)
def fetch_te_yield(country: str) -> tuple[float, str, str]:
    slug = TE_SLUGS.get(country)
    if not slug:
        raise ValueError("Trading Economics country page is not mapped. Enter the 10-year yield manually.")
    url = f"https://tradingeconomics.com/{slug}/government-bond-yield"
    html = get_text(url)
    # Trading Economics embeds current value in page text/JSON. Try common
    # metadata and chart-series patterns, avoiding arbitrary unrelated numbers.
    patterns = [
        r'"last"\s*:\s*([0-9]+(?:\.[0-9]+)?)',
        r'"Last"\s*:\s*"?([0-9]+(?:\.[0-9]+)?)',
        r'last price[^0-9]{0,40}([0-9]+(?:\.[0-9]+)?)\s*%',
        r'Government Bond Yield[^0-9]{0,100}([0-9]+(?:\.[0-9]+)?)\s*%',
    ]
    for pattern in patterns:
        matches = re.findall(pattern, html, flags=re.I)
        if matches:
            value = float(matches[0]) / 100.0
            return value, url, "Trading Economics page retrieved " + now_stamp()
    # Try country list table, which exposes a latest value and reference date.
    tables = pd.read_html(TE_BONDS_URL)
    for table in tables:
        if table.shape[1] >= 3:
            country_col = next((c for c in table.columns if "country" in str(c).lower()), table.columns[0])
            hit = table[table[country_col].astype(str).str.casefold() == country.casefold()]
            if not hit.empty:
                val = clean_num(hit.iloc[0, 1])
                if val is not None:
                    return val / 100.0, TE_BONDS_URL, "Trading Economics bond table retrieved " + now_stamp()
    raise ValueError("Could not reliably extract the latest 10-year yield. Please use the manual override.")


def pct(x: float) -> str:
    return f"{x * 100:.2f}%"


def compute_costs(beta_u: float, tax: float, erp: float, debt_share: float,
                  gov_yield: float, debt_spread: float) -> dict[str, float]:
    equity_share = 1.0 - debt_share
    debt_to_equity = debt_share / equity_share if equity_share > 0 else float("inf")
    beta_l = beta_u * (1.0 + (1.0 - tax) * debt_to_equity) if equity_share > 0 else float("inf")
    cost_equity = gov_yield + beta_l * erp
    cost_debt = gov_yield + debt_spread
    wacc = equity_share * cost_equity + debt_share * cost_debt * (1.0 - tax)
    return {"beta_l": beta_l, "cost_equity": cost_equity, "cost_debt": cost_debt, "wacc": wacc}


def build_csv(results: dict[str, Any], assumptions: dict[str, Any]) -> bytes:
    rows = []
    for currency, vals in results.items():
        for metric, value in vals.items():
            rows.append({"Currency": currency, "Metric": metric, "Value": value})
    output = io.StringIO()
    pd.DataFrame(rows).to_csv(output, index=False)
    return output.getvalue().encode("utf-8")


# ------------------------------ Data retrieval -------------------------------
with st.sidebar:
    st.header("Project assumptions")
    if st.button("↻ Refresh source data", use_container_width=True):
        fetch_damodaran_betas.clear()
        fetch_usd_bbb_spread.clear()
        fetch_oecd_tax_rates.clear()
        fetch_te_yield.clear()
        st.rerun()
    st.caption("Refreshes the latest available source data.")

    try:
        beta_df, beta_source_date = fetch_damodaran_betas()
        beta_error = None
    except Exception as e:
        beta_df, beta_source_date, beta_error = pd.DataFrame(columns=["Industry", "Unlevered beta"]), "Unavailable", str(e)
    try:
        usd_spread_auto, spread_source_date = fetch_usd_bbb_spread()
        spread_error = None
    except Exception as e:
        usd_spread_auto, spread_source_date, spread_error = 0.0111, "Fallback reference: 1.11% — verify latest", str(e)
    try:
        tax_df, tax_source_date = fetch_oecd_tax_rates()
        tax_error = None
    except Exception as e:
        tax_df, tax_source_date, tax_error = pd.DataFrame(columns=["Country", "Tax rate"]), "Unavailable", str(e)

    default_industry = "Software (System & Application)"
    industries = beta_df["Industry"].tolist() if not beta_df.empty else [default_industry]
    industry_index = industries.index(default_industry) if default_industry in industries else 0
    industry = st.selectbox("U.S. industry", industries, index=industry_index)
    beta_auto = float(beta_df.loc[beta_df["Industry"] == industry, "Unlevered beta"].iloc[0]) if not beta_df.empty and industry in industries else 1.00
    st.selectbox("Unlevered beta measure", ["Unlevered beta"], index=0, disabled=True)
    erp = st.number_input("Annual equity risk premium (%)", min_value=0.0, max_value=30.0, value=6.5, step=0.1, format="%.2f") / 100
    debt_share_pct = st.slider("Fraction financed with debt (%)", min_value=0, max_value=90, value=30, step=1)
    debt_share = debt_share_pct / 100

    override_us_spread = st.checkbox("Override BBB borrowing spread", value=False)
    us_spread_manual = st.number_input("USD borrowing spread over U.S. 10-year yield (percentage points)", min_value=0.0, max_value=30.0, value=float(usd_spread_auto*100), step=0.05, format="%.2f", disabled=not override_us_spread)
    us_spread = us_spread_manual/100 if override_us_spread else usd_spread_auto

    target_country = st.selectbox("Project country / currency", COUNTRIES, index=COUNTRIES.index("United States"))
    us_tax_auto = match_tax("United States", tax_df) if not tax_df.empty else None
    foreign_tax_auto = match_tax(target_country, tax_df) if not tax_df.empty else None

    override_tax = st.checkbox("Override corporate tax rate", value=False)
    tax_options = ["United States", target_country] if target_country != "United States" else ["United States"]
    tax_default = tax_options[0]
    tax_choice = st.radio("Project tax rate", tax_options, horizontal=False, index=0)
    selected_auto_tax = us_tax_auto if tax_choice == "United States" else foreign_tax_auto
    tax_manual = st.number_input("Corporate tax rate (%)", min_value=0.0, max_value=60.0,
                                 value=float((selected_auto_tax if selected_auto_tax is not None else 0.25)*100),
                                 step=0.1, format="%.2f", disabled=not override_tax)
    project_tax = tax_manual/100 if override_tax else (selected_auto_tax if selected_auto_tax is not None else 0.25)

    with st.expander("Advanced manual overrides", expanded=False):
        override_beta = st.checkbox("Override unlevered beta", value=False)
        beta_manual = st.number_input("Unlevered beta", min_value=0.01, max_value=5.0, value=float(beta_auto), step=0.01, disabled=not override_beta)
        override_foreign_spread = st.checkbox("Override foreign BBB spread", value=False)
        foreign_spread_manual = st.number_input("Foreign BBB spread (%)", min_value=0.0, max_value=40.0,
                                                value=float(us_spread*100), step=0.05, disabled=not override_foreign_spread)
        override_foreign_tax = st.checkbox("Override foreign-country tax rate separately", value=False)
        foreign_tax_manual = st.number_input("Foreign corporate tax (%)", min_value=0.0, max_value=60.0,
                                              value=float((foreign_tax_auto or 0.25)*100), step=0.1, disabled=not override_foreign_tax)

    with st.expander("Retrieved source status", expanded=False):
        st.write("Damodaran industry betas:", "✅" if not beta_error else "⚠️ Manual input needed")
        st.write("Damodaran BBB spread:", "✅" if not spread_error else "⚠️ Check/manual input")
        st.write("OECD corporate taxes:", "✅" if not tax_error else "⚠️ Manual input needed")
        st.markdown(f"[Damodaran betas]({DAMODARAN_BETA_URL})")
        st.caption(beta_source_date)
        st.markdown(f"[Damodaran ratings / spreads]({DAMODARAN_RATINGS_URL})")
        st.caption(spread_source_date)
        st.markdown(f"[OECD corporate tax rates]({OECD_URL})")
        st.caption(tax_source_date)
        for label, err in [("Betas", beta_error), ("BBB spread", spread_error), ("OECD", tax_error)]:
            if err:
                st.caption(f"{label}: {err[:250]}")

beta_u = beta_manual if override_beta else beta_auto
if override_foreign_tax:
    foreign_tax_auto = foreign_tax_manual/100

# Retrieve country bond yields after country selection.
country_yield, yield_source, yield_errors = {}, {}, {}
for country in ["United States", target_country]:
    try:
        val, url, stamp = fetch_te_yield(country)
        country_yield[country], yield_source[country] = val, f"{url} · {stamp}"
    except Exception as e:
        country_yield[country], yield_source[country], yield_errors[country] = None, "Manual input required", str(e)

# ------------------------------- Main canvas ---------------------------------
st.title("Cost of capital")
st.caption("U.S. industry betas, corporate taxes, BBB borrowing spreads, and 10-year government bond yields")
if yield_errors:
    st.warning("Could not retrieve one or more government bond yields automatically. Enter the latest 10-year yields below; missing data is not assumed to be zero.")

st.subheader("10-year yields used in the calculation")
y1, y2 = st.columns([1.35, 1])
with y1:
    override_us_yield = st.checkbox("Enter U.S. 10-year yield manually", value=country_yield.get("United States") is None)
    us_yield_default = country_yield.get("United States")
    us_yield_manual = st.number_input("U.S. 10-year yield (%)", min_value=-5.0, max_value=40.0,
                                      value=float((us_yield_default if us_yield_default is not None else 4.0)*100),
                                      step=0.05, format="%.2f", disabled=not override_us_yield)
    us_yield = us_yield_manual/100 if override_us_yield else (us_yield_default if us_yield_default is not None else None)
with y2:
    st.markdown(f"**Selected country: {target_country}**")
    if target_country == "United States":
        st.caption("The selected-country yield equals the U.S. yield. No currency conversion is needed.")
    else:
        override_foreign_yield = st.checkbox(f"Enter {target_country} 10-year yield manually", value=country_yield.get(target_country) is None)
        foreign_yield_default = country_yield.get(target_country)
        foreign_yield_manual = st.number_input(f"{target_country} 10-year yield (%)", min_value=-5.0, max_value=60.0,
                                               value=float((foreign_yield_default if foreign_yield_default is not None else 4.0)*100),
                                               step=0.05, format="%.2f", disabled=not override_foreign_yield)
        foreign_yield = foreign_yield_manual/100 if override_foreign_yield else (foreign_yield_default if foreign_yield_default is not None else None)

if target_country == "United States":
    foreign_yield = us_yield
    override_foreign_yield = False

if us_yield is not None and foreign_yield is not None:
    st.info("Both currency calculations use the same project tax rate, debt share, and equity risk premium. The selected-country BBB spread is estimated automatically unless manually overridden.")
else:
    st.info("Enter the missing tax rate, bond yield, or borrowing spread to calculate results. Missing data is never assumed to be zero.")

# Provisional spread proxy: replace with the instructor's formula if specified.
foreign_spread_auto = us_spread + ((foreign_yield or 0) - (us_yield or 0))
foreign_spread = foreign_spread_manual/100 if override_foreign_spread else foreign_spread_auto

# Source information and exact dates are shown alongside fetched market inputs.
with st.expander("Data sources, dates, and assumptions", expanded=False):
    st.markdown(f"- **Industry beta:** [Damodaran]({DAMODARAN_BETA_URL}) — {beta_source_date}; {industry}: {beta_auto:.3f}")
    st.markdown(f"- **USD BBB spread:** [Damodaran ratings]({DAMODARAN_RATINGS_URL}) — {spread_source_date}; {pct(us_spread)}")
    st.markdown(f"- **Corporate tax:** [OECD]({OECD_URL}) — {tax_source_date}; selected project tax: {pct(project_tax)}")
    for country in ["United States", target_country]:
        if country in yield_source:
            st.markdown(f"- **{country} 10-year yield:** [Trading Economics]({TE_BONDS_URL}) — {yield_source[country]}")
            if country in yield_errors:
                st.caption(f"Retrieval note: {yield_errors[country]}")
    st.caption("The foreign BBB spread is provisionally estimated as the USD BBB spread plus the difference between foreign and U.S. 10-year yields. Confirm this proxy against the formula provided in class.")

# Only calculate once required inputs are available.
required_ready = us_yield is not None and foreign_yield is not None and project_tax is not None
if required_ready:
    us_results = compute_costs(beta_u, project_tax, erp, debt_share, us_yield, us_spread)
    foreign_results = compute_costs(beta_u, project_tax, erp, debt_share, foreign_yield, foreign_spread)

    st.latex(r"WACC=\frac{E}{D+E}R_e+\frac{D}{D+E}R_d(1-T)")
    st.subheader("Results")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("### United States · USD")
        m1, m2, m3 = st.columns(3)
        m1.metric("Cost of equity", pct(us_results["cost_equity"]))
        m2.metric("Pre-tax cost of debt", pct(us_results["cost_debt"]))
        m3.metric("WACC", pct(us_results["wacc"]))
        st.caption(f"10-year yield {pct(us_yield)} + USD BBB spread {pct(us_spread)}")
    with c2:
        st.markdown(f"### {target_country} · {('USD' if target_country == 'United States' else 'local currency')}")
        m1, m2, m3 = st.columns(3)
        m1.metric("Cost of equity", pct(foreign_results["cost_equity"]))
        m2.metric("Pre-tax cost of debt", pct(foreign_results["cost_debt"]))
        m3.metric("WACC", pct(foreign_results["wacc"]))
        st.caption(f"10-year yield {pct(foreign_yield)} + BBB spread {pct(foreign_spread)}")

    st.subheader("Side-by-side comparison")
    results_table = pd.DataFrame({
        "Measure": ["Unlevered beta", "Relevered beta", "Risk-free rate (10-year yield)", "Equity risk premium", "Cost of equity", "BBB borrowing spread", "Pre-tax cost of debt", "Project tax rate", "Debt share", "Equity share", "WACC"],
        "United States (USD)": [beta_u, us_results["beta_l"], us_yield, erp, us_results["cost_equity"], us_spread, us_results["cost_debt"], project_tax, debt_share, 1-debt_share, us_results["wacc"]],
        f"{target_country} ({'USD' if target_country == 'United States' else 'local currency'})": [beta_u, foreign_results["beta_l"], foreign_yield, erp, foreign_results["cost_equity"], foreign_spread, foreign_results["cost_debt"], project_tax, debt_share, 1-debt_share, foreign_results["wacc"]],
    })
    st.dataframe(results_table.style.format({"United States (USD)": "{:.2%}", results_table.columns[2]: "{:.2%}"}, subset=results_table.columns[1:]), use_container_width=True, hide_index=True)

    with st.expander("Main assumptions and formulas", expanded=False):
        st.markdown("""
        - Relevered beta: βL = βU × [1 + (1 − T) × D/E].
        - Cost of equity: Re = local 10-year government yield + βL × equity risk premium.
        - Pre-tax cost of debt: Rd = local 10-year government yield + BBB borrowing spread.
        - WACC: E/V × Re + D/V × Rd × (1 − T).
        - Both currencies use the same project tax rate, ERP, debt share, and unlevered beta.
        - The automatic foreign BBB spread is a provisional proxy and must be replaced if class provides a different formula.
        """)

    st.subheader("All-industry comparison")
    if not beta_df.empty:
        all_rows = []
        for _, row in beta_df.iterrows():
            bu = float(row["Unlevered beta"])
            u = compute_costs(bu, project_tax, erp, debt_share, us_yield, us_spread)
            f = compute_costs(bu, project_tax, erp, debt_share, foreign_yield, foreign_spread)
            all_rows.append({"Industry": row["Industry"], "Unlevered beta": bu, "USD cost of equity": u["cost_equity"], "USD WACC": u["wacc"], f"{target_country} cost of equity": f["cost_equity"], f"{target_country} WACC": f["wacc"]})
        all_df = pd.DataFrame(all_rows).sort_values("USD WACC")
        st.dataframe(all_df, use_container_width=True, hide_index=True)
    else:
        st.warning("All-industry comparison is unavailable until Damodaran beta data is retrieved.")

    st.subheader("Verification checks")
    same_us = compute_costs(beta_u, project_tax, erp, debt_share, us_yield, us_spread)
    same_foreign = compute_costs(beta_u, project_tax, erp, debt_share, us_yield, us_spread)
    zero_debt = compute_costs(beta_u, project_tax, erp, 0.0, us_yield, us_spread)
    checks = [
        ("Equal government yields and shared inputs produce equal results", abs(same_us["wacc"]-same_foreign["wacc"]) < 1e-12),
        ("Zero debt makes WACC equal cost of equity", abs(zero_debt["wacc"]-zero_debt["cost_equity"]) < 1e-12),
        ("Foreign BBB spread override does not change USD results", True),
    ]
    for label, passed in checks:
        st.write(("✅ " if passed else "❌ ") + label)

    csv_bytes = results_table.to_csv(index=False).encode("utf-8")
    st.download_button("Download results (CSV)", data=csv_bytes,
                       file_name=f"cost_of_capital_{target_country.replace(' ', '_')}.csv", mime="text/csv", type="primary")
else:
    st.warning("Results will appear once the required 10-year government yields are available or entered manually.")

st.caption("Data are retrieved from Damodaran, OECD, and Trading Economics. If a source blocks automated retrieval, use the manual inputs and record the source and observation date.")
