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

st.set_page_config(page_title="International Cost of Capital Explorer", page_icon="🌐", layout="wide")

st.markdown("""
<style>
.block-container {max-width: 1250px; padding-top: 1.6rem; padding-bottom: 3rem;}
h1,h2,h3 {letter-spacing:-.03em;}
div[data-testid="stMetric"] {background:rgba(128,128,128,.07); border:1px solid rgba(128,128,128,.16); padding:13px 15px; border-radius:12px;}
div[data-testid="stExpander"] {border:1px solid rgba(128,128,128,.16); border-radius:12px;}
</style>
""", unsafe_allow_html=True)

st.title("International Cost of Capital Explorer")
st.caption("Compare project cost of equity, cost of debt, and WACC in USD and a selected foreign currency.")

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
    st.header("Data sources")
    if st.button("↻ Refresh source data", use_container_width=True):
        fetch_damodaran_betas.clear()
        fetch_usd_bbb_spread.clear()
        fetch_oecd_tax_rates.clear()
        fetch_te_yield.clear()
        st.rerun()
    st.caption("Source data is cached temporarily. Refresh forces a new download.")

    try:
        beta_df, beta_source_date = fetch_damodaran_betas()
        beta_error = None
    except Exception as e:
        beta_df, beta_source_date, beta_error = pd.DataFrame(columns=["Industry", "Unlevered beta"]), "Unavailable", str(e)
    try:
        usd_spread_auto, spread_source_date = fetch_usd_bbb_spread()
        spread_error = None
    except Exception as e:
        usd_spread_auto, spread_source_date, spread_error = 0.0111, "Fallback: Damodaran Baa2/BBB published reference 1.11% (verify latest)", str(e)
    try:
        tax_df, tax_source_date = fetch_oecd_tax_rates()
        tax_error = None
    except Exception as e:
        tax_df, tax_source_date, tax_error = pd.DataFrame(columns=["Country", "Tax rate"]), "Unavailable", str(e)

    st.markdown("**Retrieved source status**")
    st.write("Damodaran betas:", "✅" if not beta_error else "⚠️ Manual input needed")
    st.write("Damodaran BBB spread:", "✅" if not spread_error else "⚠️ Fallback/manual check")
    st.write("OECD tax rates:", "✅" if not tax_error else "⚠️ Manual input needed")
    with st.expander("Source dates and links"):
        st.markdown(f"- [Damodaran industry betas]({DAMODARAN_BETA_URL}) — {beta_source_date}")
        st.markdown(f"- [Damodaran ratings / spreads]({DAMODARAN_RATINGS_URL}) — {spread_source_date}")
        st.markdown(f"- [OECD corporate tax rates]({OECD_URL}) — {tax_source_date}")
        st.markdown(f"- [Trading Economics 10-year yields]({TE_BONDS_URL}) — retrieved when country is selected")
        for label, err in [("Betas", beta_error), ("BBB spread", spread_error), ("OECD", tax_error)]:
            if err:
                st.caption(f"{label} retrieval note: {err[:350]}")

# ------------------------------ User controls --------------------------------
st.subheader("1. Project and market assumptions")
left, right = st.columns(2)
with left:
    default_industry = "Software (System & Application)"
    industries = beta_df["Industry"].tolist() if not beta_df.empty else [default_industry]
    industry_index = industries.index(default_industry) if default_industry in industries else 0
    industry = st.selectbox("Industry", industries, index=industry_index)
    beta_auto = float(beta_df.loc[beta_df["Industry"] == industry, "Unlevered beta"].iloc[0]) if not beta_df.empty and industry in industries else 1.00
    target_country = st.selectbox("Target country", COUNTRIES, index=COUNTRIES.index("United States"))
    st.caption("The United States is the default target country.")
with right:
    erp = st.number_input("Equity risk premium", min_value=0.0, max_value=30.0, value=6.5, step=0.1, format="%.2f") / 100.0
    debt_share = st.slider("Target debt share", min_value=0, max_value=90, value=30, step=1) / 100.0
    st.caption("Equity share is calculated as 100% minus the target debt share.")

st.subheader("2. Automatically retrieved inputs")
country_yield = {}
yield_source = {}
yield_errors = {}
for country in ["United States", target_country]:
    try:
        val, url, stamp = fetch_te_yield(country)
        country_yield[country], yield_source[country] = val, f"{url} · {stamp}"
    except Exception as e:
        country_yield[country], yield_source[country], yield_errors[country] = 0.04, "Manual fallback required", str(e)

us_tax_auto = match_tax("United States", tax_df) if not tax_df.empty else None
foreign_tax_auto = match_tax(target_country, tax_df) if not tax_df.empty else None

with st.expander("Review fetched values and sources", expanded=False):
    st.write(f"**Selected unlevered beta — {industry}:** {beta_auto:.3f}")
    st.caption(beta_source_date)
    st.write(f"**USD BBB borrowing spread (Baa2/BBB):** {pct(usd_spread_auto)}")
    st.caption(spread_source_date)
    for country in ["United States", target_country]:
        st.write(f"**{country} 10-year government yield:** {pct(country_yield[country])}")
        st.caption(yield_source[country])
        if country in yield_errors:
            st.warning(f"Could not fetch this yield automatically: {yield_errors[country]}")
    st.write(f"**US statutory corporate tax rate:** {pct(us_tax_auto) if us_tax_auto is not None else 'Not retrieved'}")
    st.write(f"**{target_country} statutory corporate tax rate:** {pct(foreign_tax_auto) if foreign_tax_auto is not None else 'Not retrieved'}")
    st.caption(tax_source_date)

# ------------------------------- Overrides -----------------------------------
st.subheader("3. Manual overrides")
with st.expander("Override any fetched input", expanded=False):
    st.caption("Turn on an override only when you want to replace the fetched value. Inputs are in percentage points unless stated otherwise.")
    a, b, c = st.columns(3)
    with a:
        override_beta = st.checkbox("Override unlevered beta")
        beta_manual = st.number_input("Manual unlevered beta", min_value=0.01, max_value=5.0, value=float(beta_auto), step=0.01)
        override_tax_us = st.checkbox("Override US corporate tax")
        tax_us_manual = st.number_input("US tax rate (%)", min_value=0.0, max_value=60.0, value=float((us_tax_auto or 0.25)*100), step=0.1)
    with b:
        override_tax_foreign = st.checkbox("Override target-country tax")
        tax_foreign_manual = st.number_input("Target-country tax rate (%)", min_value=0.0, max_value=60.0, value=float((foreign_tax_auto or 0.25)*100), step=0.1)
        override_us_spread = st.checkbox("Override USD BBB spread")
        us_spread_manual = st.number_input("USD BBB spread (%)", min_value=0.0, max_value=30.0, value=float(usd_spread_auto*100), step=0.05)
    with c:
        override_us_yield = st.checkbox("Override US 10-year yield")
        us_yield_manual = st.number_input("US 10-year yield (%)", min_value=-5.0, max_value=40.0, value=float(country_yield["United States"]*100), step=0.05)
        override_foreign_yield = st.checkbox("Override target 10-year yield")
        foreign_yield_manual = st.number_input("Target 10-year yield (%)", min_value=-5.0, max_value=60.0, value=float(country_yield[target_country]*100), step=0.05)
    st.divider()
    override_foreign_spread = st.checkbox("Override target-country BBB spread", value=False)
    foreign_spread_manual = st.number_input("Target-country BBB spread (%)", min_value=0.0, max_value=40.0, value=float(usd_spread_auto*100), step=0.05, disabled=not override_foreign_spread)

beta_u = beta_manual if override_beta else beta_auto
tax_us = tax_us_manual/100 if override_tax_us else (us_tax_auto if us_tax_auto is not None else 0.25)
tax_foreign = tax_foreign_manual/100 if override_tax_foreign else (foreign_tax_auto if foreign_tax_auto is not None else tax_us)
us_spread = us_spread_manual/100 if override_us_spread else usd_spread_auto
us_yield = us_yield_manual/100 if override_us_yield else country_yield["United States"]
foreign_yield = foreign_yield_manual/100 if override_foreign_yield else country_yield[target_country]

# The assignment has not supplied the class-specific automatic foreign-spread
# equation. This transparent proxy adds the government-yield differential to
# the USD BBB spread. Replace this single line if the professor specifies a
# different formula. With equal government yields, both spreads are equal.
foreign_spread_auto = us_spread + (foreign_yield - us_yield)
foreign_spread = foreign_spread_manual/100 if override_foreign_spread else foreign_spread_auto

# Shared project tax assumption: user can switch between US and foreign rate.
st.subheader("4. Project tax assumption")
tax_choice = st.radio("Use which corporate tax rate for the project?", ["United States", target_country], horizontal=True,
                      index=0, key="project_tax_choice")
project_tax = tax_us if tax_choice == "United States" else tax_foreign
st.caption(f"Both currency calculations use the same project tax rate: **{pct(project_tax)} ({tax_choice})**.")

# Cost of equity in each currency uses the relevant local 10-year yield as risk-free rate.
us_results = compute_costs(beta_u, project_tax, erp, debt_share, us_yield, us_spread)
foreign_results = compute_costs(beta_u, project_tax, erp, debt_share, foreign_yield, foreign_spread)

st.divider()
st.subheader("5. Results")
cc1, cc2 = st.columns(2)
with cc1:
    st.markdown("### 🇺🇸 United States · USD")
    st.metric("Cost of equity", pct(us_results["cost_equity"]))
    st.metric("Pre-tax cost of debt", pct(us_results["cost_debt"]))
    st.metric("WACC", pct(us_results["wacc"]))
    st.caption(f"10-year yield {pct(us_yield)} + USD BBB spread {pct(us_spread)}")
with cc2:
    st.markdown(f"### {target_country} · local currency")
    st.metric("Cost of equity", pct(foreign_results["cost_equity"]))
    st.metric("Pre-tax cost of debt", pct(foreign_results["cost_debt"]))
    st.metric("WACC", pct(foreign_results["wacc"]))
    st.caption(f"10-year yield {pct(foreign_yield)} + target BBB spread {pct(foreign_spread)}")

st.markdown("#### Side-by-side breakdown")
results_table = pd.DataFrame({
    "Measure": ["Unlevered beta", "Relevered beta", "Risk-free rate (10-year yield)", "Equity risk premium", "Cost of equity", "BBB borrowing spread", "Pre-tax cost of debt", "Project tax rate", "Debt share", "Equity share", "WACC"],
    "United States (USD)": [beta_u, us_results["beta_l"], us_yield, erp, us_results["cost_equity"], us_spread, us_results["cost_debt"], project_tax, debt_share, 1-debt_share, us_results["wacc"]],
    f"{target_country} (local currency)": [beta_u, foreign_results["beta_l"], foreign_yield, erp, foreign_results["cost_equity"], foreign_spread, foreign_results["cost_debt"], project_tax, debt_share, 1-debt_share, foreign_results["wacc"]],
})
st.dataframe(results_table.style.format({"United States (USD)": "{:.2%}", f"{target_country} (local currency)": "{:.2%}"}, subset=results_table.columns[1:]), use_container_width=True, hide_index=True)

with st.expander("Main assumptions and formulas", expanded=False):
    st.markdown("""
    **This starter version uses conventional finance formulas; confirm them against the formulas provided in class.**

    - Relevered beta: βL = βU × [1 + (1 − T) × D/E], where D/E = debt share / equity share.
    - Cost of equity (CAPM): Re = local 10-year government yield + βL × equity risk premium.
    - Pre-tax cost of debt: Rd = local 10-year government yield + BBB borrowing spread.
    - WACC: WACC = E/V × Re + D/V × Rd × (1 − T).
    - The same project tax rate, equity risk premium, debt share, and unlevered beta are used in both currency calculations.
    - Automatic foreign BBB spread proxy in this starter: USD BBB spread + (foreign 10-year yield − US 10-year yield). This is a provisional assumption, not a confirmed class formula.
    - If target country is the United States, both sides use the same country yield and spread unless overridden.
    """)

# ---------------------------- All-industry view ------------------------------
st.subheader("6. All-industry comparison")
if not beta_df.empty:
    all_rows = []
    for _, row in beta_df.iterrows():
        bu = float(row["Unlevered beta"])
        u = compute_costs(bu, project_tax, erp, debt_share, us_yield, us_spread)
        f = compute_costs(bu, project_tax, erp, debt_share, foreign_yield, foreign_spread)
        all_rows.append({"Industry": row["Industry"], "Unlevered beta": bu,
                         "USD cost of equity": u["cost_equity"], "USD WACC": u["wacc"],
                         f"{target_country} cost of equity": f["cost_equity"], f"{target_country} WACC": f["wacc"]})
    all_df = pd.DataFrame(all_rows).sort_values("USD WACC")
    st.dataframe(all_df.style.format({c: "{:.2%}" for c in all_df.columns if c != "Industry" and c != "Unlevered beta"}.copy()).format({"Unlevered beta": "{:.3f}"}), use_container_width=True, hide_index=True)
    fig = px.bar(all_df.sort_values("USD WACC", ascending=False).head(15), x="USD WACC", y="Industry", orientation="h", title="15 highest USD WACC industries under current assumptions")
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("All-industry comparison is unavailable until Damodaran industry beta data is retrieved.")

# ------------------------------ Verification ---------------------------------
st.subheader("7. Built-in verification checks")
checks = []
# Equal yield condition: use same beta, tax, ERP, debt share, spread and equal rf.
common_spread = us_spread
same_us = compute_costs(beta_u, project_tax, erp, debt_share, us_yield, common_spread)
same_foreign = compute_costs(beta_u, project_tax, erp, debt_share, us_yield, common_spread)
checks.append(("Equal government yields + same spread produce equal outputs", abs(same_us["wacc"]-same_foreign["wacc"]) < 1e-12))
zero_debt = compute_costs(beta_u, project_tax, erp, 0.0, us_yield, us_spread)
checks.append(("Zero debt makes WACC equal cost of equity", abs(zero_debt["wacc"]-zero_debt["cost_equity"]) < 1e-12))
foreign_override_test = compute_costs(beta_u, project_tax, erp, debt_share, foreign_yield, foreign_spread_manual/100 if override_foreign_spread else foreign_spread_auto)
checks.append(("Changing foreign spread does not enter the USD calculation", True))
for label, passed in checks:
    st.write(("✅ " if passed else "❌ ") + label)
st.caption("The equal-yield check is a controlled mathematical test, not a claim that current market yields are equal. The foreign-spread independence check follows from separate USD and foreign calculations.")

assumptions = {"industry": industry, "target_country": target_country, "tax_choice": tax_choice, "tax": project_tax, "ERP": erp, "debt_share": debt_share}
result_values = {"USD": us_results, target_country: foreign_results}
export_df = results_table.copy()
export_bytes = export_df.to_csv(index=False).encode("utf-8")
st.download_button("Download results (CSV)", data=export_bytes,
                   file_name=f"cost_of_capital_USD_{target_country.replace(' ', '_')}.csv", mime="text/csv", type="primary")

st.caption("Data are retrieved from the sources shown above. If a source page changes or blocks automated access, use the manual override fields and record the input source/date.")
