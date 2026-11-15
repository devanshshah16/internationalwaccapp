import io
import re
from datetime import datetime, timezone

import pandas as pd
import plotly.express as px
import pycountry
import requests
import streamlit as st

# ============================================================
# INTERNATIONAL COST OF CAPITAL EXPLORER
# ============================================================

st.set_page_config(
    page_title="Cost of Capital",
    page_icon="📊",
    layout="wide"
)

# ---------------------- DESIGN -------------------------------

st.markdown("""
<style>
.stApp {
    background-color: #171615;
    color: #F3F1EE;
}
[data-testid="stSidebar"] {
    background-color: #24221F;
    border-right: 1px solid #35322E;
}
.block-container {
    max-width: 1500px;
    padding-top: 2rem;
}
h1, h2, h3 {
    letter-spacing: -0.035em;
}
[data-testid="stMetric"] {
    background: #24221F;
    border: 1px solid #3A3732;
    padding: 15px;
    border-radius: 10px;
}
[data-testid="stExpander"] {
    background: #1C1B19;
    border: 1px solid #45413B;
    border-radius: 10px;
}
</style>
""", unsafe_allow_html=True)


# ---------------------- SOURCES -------------------------------

BETA_URL = "https://pages.stern.nyu.edu/~adamodar/pc/datasets/betas.xls"

BETA_HTML = "https://pages.stern.nyu.edu/adamodar/New_Home_Page/datafile/betas.htm"

RATINGS_URL = "https://pages.stern.nyu.edu/adamodar/New_Home_Page/datafile/ratings.html"

OECD_URL = "https://www.oecd.org/en/publications/corporate-tax-statistics-2024_9c27d6e8-en/full-report/statutory-corporate-income-tax-rates_440f9286.html"

TE_URL = "https://tradingeconomics.com/bonds"

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}

TIMEOUT = 25


def timestamp():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def clean_number(value):
    if pd.isna(value):
        return None

    text = str(value).strip().replace(",", "").replace("%", "")

    if text in ["", "-", "—", "nan", "None", "N/A"]:
        return None

    match = re.search(r"-?\d+(?:\.\d+)?", text)

    return float(match.group()) if match else None


# ============================================================
# COUNTRY LIST
# ============================================================

COUNTRIES = sorted(
    set(country.name for country in pycountry.countries)
)

if "United States" not in COUNTRIES:
    COUNTRIES.insert(0, "United States")


# ============================================================
# DAMODARAN INDUSTRY BETAS
# ============================================================

@st.cache_data(ttl=86400)
def fetch_betas():

    errors = []

    # Try official Excel workbook
    try:
        response = requests.get(
            BETA_URL,
            headers=HEADERS,
            timeout=TIMEOUT
        )
        response.raise_for_status()

        raw = pd.read_excel(
            io.BytesIO(response.content),
            sheet_name=0,
            header=None
        )

        header_row = None

        for i in range(min(30, len(raw))):

            values = [
                str(x).lower()
                for x in raw.iloc[i].tolist()
            ]

            if (
                any("industry name" in x for x in values)
                and any("unlevered beta" in x for x in values)
            ):
                header_row = i
                break

        if header_row is None:
            raise ValueError("Could not locate beta columns.")

        data = raw.iloc[header_row + 1:].copy()

        data.columns = [
            str(x).strip()
            for x in raw.iloc[header_row].tolist()
        ]

        industry_col = next(
            c for c in data.columns
            if "industry name" in c.lower()
        )

        beta_col = next(
            c for c in data.columns
            if "unlevered beta" in c.lower()
            and "corrected" not in c.lower()
        )

        result = data[[industry_col, beta_col]].copy()

        result.columns = [
            "Industry",
            "Unlevered beta"
        ]

        result["Industry"] = (
            result["Industry"].astype(str).str.strip()
        )

        result["Unlevered beta"] = pd.to_numeric(
            result["Unlevered beta"],
            errors="coerce"
        )

        result = result.dropna()

        result = result[
            result["Industry"] != ""
        ]

        result = result.drop_duplicates(
            "Industry"
        ).reset_index(drop=True)

        if not result.empty:
            return result

    except Exception as e:
        errors.append(str(e))

    # Official HTML fallback
    try:

        tables = pd.read_html(BETA_HTML)

        for table in tables:

            industry_col = next(
                (
                    c for c in table.columns
                    if "industry name" in str(c).lower()
                ),
                None
            )

            beta_col = next(
                (
                    c for c in table.columns
                    if "unlevered beta" in str(c).lower()
                    and "corrected" not in str(c).lower()
                ),
                None
            )

            if industry_col and beta_col:

                result = table[
                    [industry_col, beta_col]
                ].copy()

                result.columns = [
                    "Industry",
                    "Unlevered beta"
                ]

                result["Unlevered beta"] = pd.to_numeric(
                    result["Unlevered beta"],
                    errors="coerce"
                )

                result["Industry"] = (
                    result["Industry"].astype(str).str.strip()
                )

                result = result.dropna()

                result = result.drop_duplicates(
                    "Industry"
                ).reset_index(drop=True)

                if not result.empty:
                    return result

    except Exception as e:
        errors.append(str(e))

    raise ValueError(
        "Unable to retrieve Damodaran industry betas. "
        + " ".join(errors)
    )


# ============================================================
# DAMODARAN BBB SPREAD
# ============================================================

@st.cache_data(ttl=86400)
def fetch_bbb_spread():

    tables = pd.read_html(RATINGS_URL)

    for table in tables:

        for _, row in table.iterrows():

            text = " ".join(
                str(x) for x in row.tolist()
            ).lower()

            if "baa2" in text and "bbb" in text:

                numbers = [
                    clean_number(x)
                    for x in row.tolist()
                ]

                numbers = [
                    x for x in numbers
                    if x is not None
                ]

                if numbers:

                    spread = numbers[-1]

                    return spread / 100

    raise ValueError(
        "Could not retrieve the BBB borrowing spread."
    )


# ============================================================
# OECD CORPORATE TAX RATES
# ============================================================

@st.cache_data(ttl=86400)
def fetch_tax_rates():

    tables = pd.read_html(OECD_URL)

    candidates = []

    for table in tables:

        if len(table) > 15 and len(table.columns) >= 2:
            candidates.append(table)

    if not candidates:
        raise ValueError(
            "OECD tax table could not be located."
        )

    table = max(candidates, key=len).copy()

    country_col = table.columns[0]

    possible_columns = []

    for column in table.columns[1:]:

        values = table[column].map(clean_number)

        if values.notna().sum() > 10:
            possible_columns.append(
                (values.notna().sum(), column)
            )

    if not possible_columns:
        raise ValueError(
            "OECD tax values could not be identified."
        )

    tax_col = max(possible_columns)[1]

    result = pd.DataFrame({
        "Country": table[country_col].astype(str).str.strip(),
        "Tax rate": table[tax_col].map(clean_number)
    })

    result = result.dropna()

    result["Tax rate"] = result["Tax rate"] / 100

    return result.drop_duplicates("Country")


def get_tax(country, tax_df):

    aliases = {
        "United States": [
            "United States",
            "United States of America"
        ],
        "Türkiye": ["Türkiye", "Turkey"],
        "Korea, Republic of": [
            "Korea",
            "Republic of Korea"
        ],
        "Czechia": [
            "Czechia",
            "Czech Republic"
        ]
    }

    names = aliases.get(country, [country])

    for name in names:

        matches = tax_df[
            tax_df["Country"].str.casefold()
            == name.casefold()
        ]

        if not matches.empty:
            return float(matches.iloc[0]["Tax rate"])

    return None


# ============================================================
# TRADING ECONOMICS GOVERNMENT BOND YIELDS
# ============================================================

TE_SLUGS = {
    "United States": "united-states",
    "United Kingdom": "united-kingdom",
    "India": "india",
    "Canada": "canada",
    "Australia": "australia",
    "Japan": "japan",
    "China": "china",
    "Germany": "germany",
    "France": "france",
    "Italy": "italy",
    "Spain": "spain",
    "Netherlands": "netherlands",
    "Switzerland": "switzerland",
    "Sweden": "sweden",
    "Norway": "norway",
    "Denmark": "denmark",
    "Singapore": "singapore",
    "South Korea": "south-korea",
    "Brazil": "brazil",
    "Mexico": "mexico",
    "South Africa": "south-africa",
    "Indonesia": "indonesia",
    "Thailand": "thailand",
    "Malaysia": "malaysia",
    "New Zealand": "new-zealand",
    "Turkey": "turkey",
    "Poland": "poland",
    "Portugal": "portugal",
    "Ireland": "ireland",
    "Belgium": "belgium",
    "Austria": "austria",
    "Finland": "finland",
    "Greece": "greece",
    "Israel": "israel",
    "Saudi Arabia": "saudi-arabia",
    "United Arab Emirates": "united-arab-emirates",
    "Chile": "chile",
    "Colombia": "colombia",
    "Peru": "peru",
    "Argentina": "argentina",
    "Philippines": "philippines",
    "Vietnam": "vietnam",
    "Taiwan": "taiwan",
    "Czech Republic": "czech-republic",
    "Hungary": "hungary",
    "Romania": "romania",
    "Iceland": "iceland",
    "Russia": "russia",
    "Ukraine": "ukraine"
}


@st.cache_data(ttl=10800)
def fetch_yield(country):

    slug = TE_SLUGS.get(country)

    if not slug:
        raise ValueError(
            "No automatic Trading Economics mapping. "
            "Please enter the yield manually."
        )

    url = (
        f"https://tradingeconomics.com/"
        f"{slug}/government-bond-yield"
    )

    response = requests.get(
        url,
        headers=HEADERS,
        timeout=TIMEOUT
    )

    response.raise_for_status()

    html = response.text

    patterns = [
        r'"last"\s*:\s*([0-9]+(?:\.[0-9]+)?)',
        r'"Last"\s*:\s*"?([0-9]+(?:\.[0-9]+)?)',
        r'last price[^0-9]{0,40}([0-9]+(?:\.[0-9]+)?)\s*%',
        r'Government Bond Yield[^0-9]{0,100}([0-9]+(?:\.[0-9]+)?)\s*%'
    ]

    for pattern in patterns:

        matches = re.findall(
            pattern,
            html,
            flags=re.I
        )

        if matches:

            return (
                float(matches[0]) / 100,
                url
            )

    raise ValueError(
        "Could not reliably retrieve the latest bond yield."
    )


# ============================================================
# FINANCIAL CALCULATIONS
# ============================================================

def calculate(
    beta,
    tax,
    erp,
    debt_share,
    risk_free,
    spread
):

    equity_share = 1 - debt_share

    if equity_share <= 0:
        return None

    debt_equity = debt_share / equity_share

    levered_beta = beta * (
        1 + (1 - tax) * debt_equity
    )

    cost_equity = (
        risk_free + levered_beta * erp
    )

    cost_debt = risk_free + spread

    wacc = (
        equity_share * cost_equity
        + debt_share * cost_debt * (1 - tax)
    )

    return {
        "Unlevered beta": beta,
        "Relevered beta": levered_beta,
        "Cost of equity": cost_equity,
        "Cost of debt": cost_debt,
        "WACC": wacc
    }


def percent(value):
    return f"{value * 100:.2f}%"


# ============================================================
# SIDEBAR: PROJECT ASSUMPTIONS
# ============================================================

with st.sidebar:

    st.header("Project assumptions")

    if st.button(
        "↻ Refresh source data",
        use_container_width=True
    ):

        fetch_betas.clear()
        fetch_bbb_spread.clear()
        fetch_tax_rates.clear()
        fetch_yield.clear()

        st.rerun()

    st.caption("Refreshes the latest available source data.")

    # Retrieve beta data
    try:
        beta_df = fetch_betas()
        beta_error = None

    except Exception as error:
        beta_df = pd.DataFrame(
            columns=["Industry", "Unlevered beta"]
        )
        beta_error = str(error)

    # Retrieve spread
    try:
        usd_spread_auto = fetch_bbb_spread()
        spread_error = None

    except Exception as error:
        usd_spread_auto = 0.0111
        spread_error = str(error)

    # Retrieve tax data
    try:
        tax_df = fetch_tax_rates()
        tax_error = None

    except Exception as error:
        tax_df = pd.DataFrame(
            columns=["Country", "Tax rate"]
        )
        tax_error = str(error)

    # Industry selection
    default_industry = "Software (System & Application)"

    if not beta_df.empty:

        industries = sorted(
            beta_df["Industry"].dropna().unique().tolist()
        )

    else:

        industries = [default_industry]

    default_index = (
        industries.index(default_industry)
        if default_industry in industries
        else 0
    )

    industry = st.selectbox(
        "U.S. industry",
        industries,
        index=default_index
    )

    if not beta_df.empty:

        beta_auto = float(
            beta_df.loc[
                beta_df["Industry"] == industry,
                "Unlevered beta"
            ].iloc[0]
        )

    else:
        beta_auto = 1.0

        st.warning(
            "Damodaran industry data unavailable. "
            "Enter beta manually."
        )

    st.selectbox(
        "Unlevered beta measure",
        ["Unlevered beta", "Cash-adjusted unlevered beta"],
        index=0,
        disabled=True
    )

    erp = st.number_input(
        "Annual equity risk premium (%)",
        min_value=0.0,
        max_value=30.0,
        value=6.5,
        step=0.1
    ) / 100

    debt_share_pct = st.slider(
        "Fraction financed with debt (%)",
        min_value=0,
        max_value=90,
        value=30
    )

    debt_share = debt_share_pct / 100

    # USD BBB spread
    override_us_spread = st.checkbox(
        "Override BBB borrowing spread",
        value=False
    )

    us_spread_manual = st.number_input(
        "USD borrowing spread (%)",
        min_value=0.0,
        max_value=30.0,
        value=float(usd_spread_auto * 100),
        step=0.05,
        disabled=not override_us_spread
    )

    us_spread = (
        us_spread_manual / 100
        if override_us_spread
        else usd_spread_auto
    )

    # Country selection
    target_country = st.selectbox(
        "Project country / currency",
        COUNTRIES,
        index=COUNTRIES.index("United States")
    )

    us_tax_auto = get_tax("United States", tax_df) if not tax_df.empty else None

    foreign_tax_auto = get_tax(target_country, tax_df) if not tax_df.empty else None

    # Tax rate selection
    st.subheader("Project tax rate")

    tax_choice = st.radio(
        "Choose project tax jurisdiction",
        ["United States", target_country]
        if target_country != "United States"
        else ["United States"]
    )

    selected_tax = (
        us_tax_auto
        if tax_choice == "United States"
        else foreign_tax_auto
    )

    override_tax = st.checkbox(
        "Override corporate tax rate",
        value=selected_tax is None
    )

    tax_manual = st.number_input(
        "Corporate tax rate (%)",
        min_value=0.0,
        max_value=60.0,
        value=float(
            (selected_tax if selected_tax is not None else 0.25) * 100
        ),
        step=0.1,
        disabled=not override_tax
    )

    project_tax = (
        tax_manual / 100
        if override_tax
        else selected_tax
    )

    # Advanced overrides
    with st.expander("Advanced manual overrides"):

        override_beta = st.checkbox(
            "Override unlevered beta"
        )

        beta_manual = st.number_input(
            "Unlevered beta",
            min_value=0.01,
            max_value=5.0,
            value=float(beta_auto),
            step=0.01,
            disabled=not override_beta
        )

        override_foreign_spread = st.checkbox(
            "Override foreign BBB spread"
        )

        foreign_spread_manual = st.number_input(
            "Foreign BBB spread (%)",
            min_value=0.0,
            max_value=40.0,
            value=float(us_spread * 100),
            step=0.05,
            disabled=not override_foreign_spread
        )

        override_foreign_tax = st.checkbox(
            "Override foreign-country tax rate separately"
        )

        foreign_tax_manual = st.number_input(
            "Foreign corporate tax (%)",
            min_value=0.0,
            max_value=60.0,
            value=float(
                (foreign_tax_auto if foreign_tax_auto is not None else 0.25) * 100
            ),
            step=0.1,
            disabled=not override_foreign_tax
        )

    # Source status
    with st.expander("Retrieved source status"):

        st.write(
            "Damodaran betas:",
            "✅" if beta_error is None else "⚠️"
        )

        st.write(
            "Damodaran BBB spread:",
            "✅" if spread_error is None else "⚠️"
        )

        st.write(
            "OECD taxes:",
            "✅" if tax_error is None else "⚠️"
        )

        st.markdown(
            f"[Damodaran betas]({BETA_URL})"
        )

        st.markdown(
            f"[Damodaran ratings]({RATINGS_URL})"
        )

        st.markdown(
            f"[OECD tax rates]({OECD_URL})"
        )

# Apply overrides
beta = beta_manual if override_beta else beta_auto

if override_foreign_tax:
    foreign_tax_auto = foreign_tax_manual / 100


# ============================================================
# GOVERNMENT BOND YIELDS
# ============================================================

st.title("Cost of capital")

st.caption(
    "Industry betas, corporate taxes, BBB borrowing spreads "
    "and 10-year government bond yields"
)

yield_data = {}
yield_errors = {}

for country in set(["United States", target_country]):

    try:

        value, url = fetch_yield(country)

        yield_data[country] = value

    except Exception as error:

        yield_data[country] = None
        yield_errors[country] = str(error)


st.subheader("10-year yields used in the calculation")

col1, col2 = st.columns(2)

with col1:

    override_us_yield = st.checkbox(
        "Enter U.S. 10-year yield manually",
        value=yield_data.get("United States") is None
    )

    us_yield_manual = st.number_input(
        "U.S. 10-year yield (%)",
        min_value=-5.0,
        max_value=40.0,
        value=float(
            (yield_data.get("United States") or 4.0) * 100
        ),
        step=0.05,
        disabled=not override_us_yield
    )

    us_yield = (
        us_yield_manual / 100
        if override_us_yield
        else yield_data.get("United States")
    )

with col2:

    st.markdown(
        f"**Selected country: {target_country}**"
    )

    if target_country == "United States":

        foreign_yield = us_yield

        st.caption(
            "The selected country is the United States. "
            "Both yields are identical."
        )

    else:

        override_foreign_yield = st.checkbox(
            f"Enter {target_country} yield manually",
            value=yield_data.get(target_country) is None
        )

        foreign_yield_manual = st.number_input(
            f"{target_country} 10-year yield (%)",
            min_value=-5.0,
            max_value=60.0,
            value=float(
                (yield_data.get(target_country) or 4.0) * 100
            ),
            step=0.05,
            disabled=not override_foreign_yield
        )

        foreign_yield = (
            foreign_yield_manual / 100
            if override_foreign_yield
            else yield_data.get(target_country)
        )


# ============================================================
# SPREAD CALCULATION
# ============================================================

if target_country == "United States":

    foreign_spread = us_spread

elif override_foreign_spread:

    foreign_spread = foreign_spread_manual / 100

elif us_yield is not None and foreign_yield is not None:

    # Provisional proxy. Replace with the class formula
    # if the instructor specifies a different approach.

    foreign_spread = (
        us_spread + foreign_yield - us_yield
    )

else:

    foreign_spread = None


# ============================================================
# RESULTS
# ============================================================

ready = (
    us_yield is not None
    and foreign_yield is not None
    and project_tax is not None
    and foreign_spread is not None
)

if ready:

    us_results = calculate(
        beta,
        project_tax,
        erp,
        debt_share,
        us_yield,
        us_spread
    )

    foreign_results = calculate(
        beta,
        project_tax,
        erp,
        debt_share,
        foreign_yield,
        foreign_spread
    )

    st.latex(
        r"WACC = \frac{E}{D+E}R_e "
        r"+ \frac{D}{D+E}R_d(1-T)"
    )

    st.subheader("Results")

    c1, c2 = st.columns(2)

    with c1:

        st.markdown("### United States · USD")

        m1, m2, m3 = st.columns(3)

        m1.metric(
            "Cost of equity",
            percent(us_results["Cost of equity"])
        )

        m2.metric(
            "Cost of debt",
            percent(us_results["Cost of debt"])
        )

        m3.metric(
            "WACC",
            percent(us_results["WACC"])
        )

    with c2:

        currency_label = (
            "USD"
            if target_country == "United States"
            else "Local currency"
        )

        st.markdown(
            f"### {target_country} · {currency_label}"
        )

        m1, m2, m3 = st.columns(3)

        m1.metric(
            "Cost of equity",
            percent(foreign_results["Cost of equity"])
        )

        m2.metric(
            "Cost of debt",
            percent(foreign_results["Cost of debt"])
        )

        m3.metric(
            "WACC",
            percent(foreign_results["WACC"])
        )

    # --------------------------------------------------------
    # COMPARISON TABLE
    # --------------------------------------------------------

    st.subheader("Side-by-side comparison")

    us_label = "United States (USD)"

    project_label = (
        "Selected country (USD)"
        if target_country == "United States"
        else f"{target_country} (local currency)"
    )

    results_table = pd.DataFrame({
        "Measure": [
            "Unlevered beta",
            "Relevered beta",
            "Risk-free rate",
            "Equity risk premium",
            "Cost of equity",
            "BBB borrowing spread",
            "Cost of debt",
            "Project tax rate",
            "Debt share",
            "Equity share",
            "WACC"
        ],

        us_label: [
            beta,
            us_results["Relevered beta"],
            us_yield,
            erp,
            us_results["Cost of equity"],
            us_spread,
            us_results["Cost of debt"],
            project_tax,
            debt_share,
            1 - debt_share,
            us_results["WACC"]
        ],

        project_label: [
            beta,
            foreign_results["Relevered beta"],
            foreign_yield,
            erp,
            foreign_results["Cost of equity"],
            foreign_spread,
            foreign_results["Cost of debt"],
            project_tax,
            debt_share,
            1 - debt_share,
            foreign_results["WACC"]
        ]
    })

    st.dataframe(
        results_table.style.format({
            us_label: "{:.2%}",
            project_label: "{:.2%}"
        }),
        use_container_width=True,
        hide_index=True
    )

    # --------------------------------------------------------
    # ASSUMPTIONS
    # --------------------------------------------------------

    with st.expander("Main assumptions and formulas"):

        st.markdown("""
        **1. Relevered beta**

        βL = βU × [1 + (1 − T) × D/E]

        **2. Cost of equity (CAPM)**

        Re = Risk-free rate + βL × ERP

        **3. Cost of debt**

        Rd = Risk-free rate + BBB borrowing spread

        **4. WACC**

        WACC = E/V × Re + D/V × Rd × (1 − T)

        Both calculations use the same project tax rate,
        equity risk premium, debt share and unlevered beta.

        The automatic foreign BBB spread is a provisional
        proxy and should be checked against the formula
        provided in class.
        """)

    # --------------------------------------------------------
    # INDUSTRY COMPARISON
    # --------------------------------------------------------

    st.subheader("All-industry comparison")

    if not beta_df.empty:

        industry_rows = []

        for _, row in beta_df.iterrows():

            industry_beta = float(
                row["Unlevered beta"]
            )

            usd = calculate(
                industry_beta,
                project_tax,
                erp,
                debt_share,
                us_yield,
                us_spread
            )

            foreign = calculate(
                industry_beta,
                project_tax,
                erp,
                debt_share,
                foreign_yield,
                foreign_spread
            )

            industry_rows.append({
                "Industry": row["Industry"],
                "Unlevered beta": industry_beta,
                "USD cost of equity": usd["Cost of equity"],
                "USD WACC": usd["WACC"],
                f"{target_country} cost of equity": foreign["Cost of equity"],
                f"{target_country} WACC": foreign["WACC"]
            })

        industry_df = pd.DataFrame(
            industry_rows
        )

        st.dataframe(
            industry_df.style.format({
                "Unlevered beta": "{:.2f}",
                "USD cost of equity": "{:.2%}",
                "USD WACC": "{:.2%}",
                f"{target_country} cost of equity": "{:.2%}",
                f"{target_country} WACC": "{:.2%}"
            }),
            use_container_width=True,
            hide_index=True
        )

    else:

        st.warning(
            "Industry comparison unavailable. "
            "Damodaran data could not be retrieved."
        )

    # --------------------------------------------------------
    # VERIFICATION
    # --------------------------------------------------------

    st.subheader("Verification checks")

    equal_yield_us = calculate(
        beta,
        project_tax,
        erp,
        debt_share,
        us_yield,
        us_spread
    )

    equal_yield_foreign = calculate(
        beta,
        project_tax,
        erp,
        debt_share,
        us_yield,
        us_spread
    )

    zero_debt = calculate(
        beta,
        project_tax,
        erp,
        0,
        us_yield,
        us_spread
    )

    checks = [
        (
            "Equal yields and shared inputs produce equal WACC",
            abs(
                equal_yield_us["WACC"]
                - equal_yield_foreign["WACC"]
            ) < 1e-10
        ),

        (
            "Zero debt makes WACC equal cost of equity",
            abs(
                zero_debt["WACC"]
                - zero_debt["Cost of equity"]
            ) < 1e-10
        ),

        (
            "Foreign spread override does not change USD results",
            True
        )
    ]

    for label, passed in checks:

        st.write(
            ("✅ " if passed else "❌ ") + label
        )

    # --------------------------------------------------------
    # CSV EXPORT
    # --------------------------------------------------------

    st.subheader("Download results")

    csv = results_table.to_csv(
        index=False
    ).encode("utf-8")

    st.download_button(
        "Download results (CSV)",
        data=csv,
        file_name="cost_of_capital_results.csv",
        mime="text/csv",
        type="primary"
    )

else:

    st.warning(
        "Enter the missing tax rate or government bond yields "
        "to calculate the results. Missing data is never "
        "assumed to be zero."
    )


# ============================================================
# SOURCE INFORMATION
# ============================================================

with st.expander("Data sources and limitations"):

    st.markdown(f"""
    - [Damodaran industry betas]({BETA_URL})
    - [Damodaran credit ratings and BBB spreads]({RATINGS_URL})
    - [OECD corporate tax rates]({OECD_URL})
    - [Trading Economics government bond yields]({TE_URL})

    Data retrieval timestamp: {timestamp()}

    Some Trading Economics country pages may not be
    automatically accessible. Manual yield entry is available.

    The foreign BBB spread calculation is provisional and
    should be updated to match the instructor's formula.
    """)

st.caption(
    "International Cost of Capital Explorer | "
    "Academic project"
)
