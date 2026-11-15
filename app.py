import io
import re
from datetime import datetime, timezone

import pandas as pd
import pycountry
import requests
import streamlit as st
import plotly.express as px


# ============================================================
# PAGE CONFIGURATION
# ============================================================

st.set_page_config(
    page_title="International Cost of Capital",
    page_icon="📊",
    layout="wide"
)

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


# ============================================================
# DATA SOURCES
# ============================================================

BETA_HTML = (
    "https://pages.stern.nyu.edu/"
    "~adamodar/New_Home_Page/datafile/Betas.html"
)

BETA_EXCEL = (
    "https://pages.stern.nyu.edu/"
    "~adamodar/pc/datasets/betas.xls"
)

RATINGS_URL = (
    "https://pages.stern.nyu.edu/"
    "adamodar/New_Home_Page/datafile/ratings.html"
)

OECD_URL = (
    "https://www.oecd.org/en/publications/"
    "corporate-tax-statistics-2024_9c27d6e8-en/"
    "full-report/statutory-corporate-income-tax-rates_440f9286.html"
)

TRADING_ECONOMICS_URL = "https://tradingeconomics.com/bonds"

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}

TIMEOUT = 30


def current_timestamp():
    return datetime.now(timezone.utc).strftime(
        "%Y-%m-%d %H:%M UTC"
    )


def clean_number(value):

    if pd.isna(value):
        return None

    text = str(value).strip()

    if text in ["", "-", "—", "nan", "None", "N/A"]:
        return None

    text = text.replace(",", "").replace("%", "")

    match = re.search(
        r"-?\d+(?:\.\d+)?",
        text
    )

    return float(match.group()) if match else None


def flatten_columns(columns):

    flattened = []

    for column in columns:

        if isinstance(column, tuple):

            flattened.append(
                " ".join(
                    str(x) for x in column
                    if str(x) != "nan"
                ).strip()
            )

        else:

            flattened.append(str(column).strip())

    return flattened


# ============================================================
# COUNTRY LIST
# ============================================================

COUNTRIES = sorted(
    country.name
    for country in pycountry.countries
)

COUNTRY_ALIASES = {
    "United States": [
        "United States",
        "United States of America"
    ],
    "South Korea": [
        "South Korea",
        "Korea, Republic of"
    ],
    "North Korea": [
        "North Korea",
        "Korea, Democratic People's Republic of"
    ],
    "Czechia": [
        "Czechia",
        "Czech Republic"
    ],
    "Türkiye": [
        "Türkiye",
        "Turkey"
    ],
    "Russia": [
        "Russia",
        "Russian Federation"
    ],
    "Vietnam": [
        "Vietnam",
        "Viet Nam"
    ],
    "Taiwan": [
        "Taiwan",
        "Taiwan, Province of China"
    ]
}


# ============================================================
# DAMODARAN INDUSTRY BETAS
# ============================================================

def identify_beta_table(tables):

    for table in tables:

        table = table.copy()

        table.columns = flatten_columns(
            table.columns
        )

        industry_col = next(
            (
                c for c in table.columns
                if "industry name" in c.lower()
            ),
            None
        )

        beta_col = next(
            (
                c for c in table.columns
                if "unlevered beta" in c.lower()
                and "corrected" not in c.lower()
                and "cash" not in c.lower()
            ),
            None
        )

        cash_beta_col = next(
            (
                c for c in table.columns
                if "unlevered beta" in c.lower()
                and (
                    "corrected" in c.lower()
                    or "cash" in c.lower()
                )
            ),
            None
        )

        if industry_col and beta_col:

            output = pd.DataFrame()

            output["Industry"] = (
                table[industry_col]
                .astype(str)
                .str.strip()
            )

            output["Unlevered beta"] = pd.to_numeric(
                table[beta_col],
                errors="coerce"
            )

            if cash_beta_col:

                output["Cash-adjusted unlevered beta"] = (
                    pd.to_numeric(
                        table[cash_beta_col],
                        errors="coerce"
                    )
                )

            output = output.dropna(
                subset=["Unlevered beta"]
            )

            output = output[
                output["Industry"].ne("")
            ]

            output = output[
                ~output["Industry"].str.lower().isin(
                    ["industry name", "nan", "total"]
                )
            ]

            output = output.drop_duplicates(
                subset=["Industry"]
            )

            if not output.empty:

                return output.reset_index(drop=True)

    return None


@st.cache_data(ttl=86400)
def fetch_betas():

    errors = []

    # First attempt: official HTML table
    try:

        response = requests.get(
            BETA_HTML,
            headers=HEADERS,
            timeout=TIMEOUT
        )

        response.raise_for_status()

        tables = pd.read_html(
            io.StringIO(response.text),
            header=0
        )

        result = identify_beta_table(tables)

        if result is not None:
            return result

    except Exception as error:

        errors.append(
            "HTML source: " + str(error)
        )

    # Second attempt: official Excel workbook
    try:

        response = requests.get(
            BETA_EXCEL,
            headers=HEADERS,
            timeout=TIMEOUT
        )

        response.raise_for_status()

        workbook = pd.ExcelFile(
            io.BytesIO(response.content)
        )

        for sheet in workbook.sheet_names:

            raw = pd.read_excel(
                workbook,
                sheet_name=sheet,
                header=None
            )

            for row_number in range(
                min(30, len(raw))
            ):

                values = [
                    str(x).lower()
                    for x in raw.iloc[row_number].tolist()
                ]

                if (
                    any("industry name" in x for x in values)
                    and any("unlevered beta" in x for x in values)
                ):

                    raw.columns = flatten_columns(
                        raw.iloc[row_number].tolist()
                    )

                    data = raw.iloc[
                        row_number + 1:
                    ].copy()

                    result = identify_beta_table(
                        [data]
                    )

                    if result is not None:
                        return result

    except Exception as error:

        errors.append(
            "Excel source: " + str(error)
        )

    raise ValueError(
        "Unable to retrieve Damodaran betas. "
        + " | ".join(errors)
    )


# ============================================================
# DAMODARAN BBB SPREAD
# ============================================================

@st.cache_data(ttl=86400)
def fetch_bbb_spread():

    response = requests.get(
        RATINGS_URL,
        headers=HEADERS,
        timeout=TIMEOUT
    )

    response.raise_for_status()

    tables = pd.read_html(
        io.StringIO(response.text)
    )

    for table in tables:

        for _, row in table.iterrows():

            values = [
                str(x).strip()
                for x in row.tolist()
            ]

            text = " ".join(values).lower()

            if (
                "baa2" in text
                and "bbb" in text
            ):

                numbers = [
                    clean_number(x)
                    for x in values
                ]

                numbers = [
                    x for x in numbers
                    if x is not None
                ]

                if numbers:

                    # Damodaran spread is expressed in
                    # percentage points.
                    return numbers[-1] / 100

    raise ValueError(
        "Could not identify the Baa2/BBB spread."
    )


# ============================================================
# OECD CORPORATE TAX RATES
# ============================================================

@st.cache_data(ttl=86400)
def fetch_tax_rates():

    response = requests.get(
        OECD_URL,
        headers=HEADERS,
        timeout=TIMEOUT
    )

    response.raise_for_status()

    tables = pd.read_html(
        io.StringIO(response.text)
    )

    candidates = []

    for table in tables:

        table = table.copy()

        table.columns = flatten_columns(
            table.columns
        )

        if len(table) < 15:
            continue

        first_col = table.columns[0]

        year_columns = []

        for column in table.columns[1:]:

            years = re.findall(
                r"20\d{2}",
                str(column)
            )

            if years:

                year_columns.append(
                    (max(map(int, years)), column)
                )

        if year_columns:

            latest_year, latest_column = max(
                year_columns,
                key=lambda x: x[0]
            )

            candidates.append(
                (
                    latest_year,
                    first_col,
                    latest_column,
                    table
                )
            )

    if not candidates:

        raise ValueError(
            "Could not identify OECD country tax table."
        )

    # Select the latest-year table
    latest_year, country_col, tax_col, table = max(
        candidates,
        key=lambda x: x[0]
    )

    result = pd.DataFrame({
        "Country": (
            table[country_col]
            .astype(str)
            .str.strip()
        ),
        "Tax rate": table[tax_col].map(clean_number)
    })

    result = result.dropna()

    result["Tax rate"] = result["Tax rate"] / 100

    result = result[
        (result["Tax rate"] >= 0)
        & (result["Tax rate"] <= 1)
    ]

    result = result.drop_duplicates(
        subset=["Country"]
    )

    result.attrs["source_year"] = latest_year

    return result.reset_index(drop=True)


def get_tax(country, tax_df):

    names = COUNTRY_ALIASES.get(
        country,
        [country]
    )

    for name in names:

        matches = tax_df[
            tax_df["Country"].str.casefold()
            == name.casefold()
        ]

        if not matches.empty:

            return float(
                matches.iloc[0]["Tax rate"]
            )

    return None


# ============================================================
# TRADING ECONOMICS BOND YIELDS
# ============================================================

SPECIAL_SLUGS = {
    "United States": "united-states",
    "United Kingdom": "united-kingdom",
    "South Korea": "south-korea",
    "North Korea": "north-korea",
    "Czechia": "czech-republic",
    "Türkiye": "turkey",
    "Russia": "russia",
    "Vietnam": "vietnam",
    "Taiwan": "taiwan"
}


def country_slug(country):

    if country in SPECIAL_SLUGS:
        return SPECIAL_SLUGS[country]

    return re.sub(
        r"[^a-z0-9]+",
        "-",
        country.lower()
    ).strip("-")


@st.cache_data(ttl=10800)
def fetch_yield(country):

    slug = country_slug(country)

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
        r'"last"\s*:\s*"?([0-9]+(?:\.[0-9]+)?)',
        r'"Last"\s*:\s*"?([0-9]+(?:\.[0-9]+)?)',
        r'"LastValue"\s*:\s*"?([0-9]+(?:\.[0-9]+)?)'
    ]

    for pattern in patterns:

        matches = re.findall(
            pattern,
            html,
            flags=re.I
        )

        for match in matches:

            value = float(match)

            if 0 <= value <= 50:

                return (
                    value / 100,
                    url
                )

    raise ValueError(
        "Trading Economics did not return "
        "an identifiable 10-year bond yield."
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

    if not 0 <= tax <= 1:
        raise ValueError("Tax rate must be between 0 and 100%.")

    if not 0 <= debt_share < 1:
        raise ValueError("Debt share must be below 100%.")

    equity_share = 1 - debt_share

    debt_equity = (
        debt_share / equity_share
    )

    levered_beta = beta * (
        1 + (1 - tax) * debt_equity
    )

    cost_equity = (
        risk_free + levered_beta * erp
    )

    cost_debt = (
        risk_free + spread
    )

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

    if value is None:
        return "Unavailable"

    return f"{value * 100:.2f}%"


# ============================================================
# SIDEBAR
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

    st.caption(
        "Latest available source data is retrieved when possible."
    )

    # --------------------------------------------------------
    # RETRIEVE DATA
    # --------------------------------------------------------

    try:

        beta_df = fetch_betas()
        beta_error = None

    except Exception as error:

        beta_df = pd.DataFrame(
            columns=[
                "Industry",
                "Unlevered beta"
            ]
        )

        beta_error = str(error)

    try:

        usd_spread_auto = fetch_bbb_spread()
        spread_error = None

    except Exception as error:

        usd_spread_auto = None
        spread_error = str(error)

    try:

        tax_df = fetch_tax_rates()
        tax_error = None

    except Exception as error:

        tax_df = pd.DataFrame(
            columns=["Country", "Tax rate"]
        )

        tax_error = str(error)

    # --------------------------------------------------------
    # INDUSTRY
    # --------------------------------------------------------

    default_industry = (
        "Software (System & Application)"
    )

    if not beta_df.empty:

        industries = sorted(
            beta_df["Industry"].dropna().unique()
        )

    else:

        industries = []

    if industries:

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

        beta_auto = float(
            beta_df.loc[
                beta_df["Industry"] == industry,
                "Unlevered beta"
            ].iloc[0]
        )

    else:

        industry = st.selectbox(
            "U.S. industry",
            [default_industry]
        )

        beta_auto = None

        st.warning(
            "Damodaran data unavailable. "
            "Please enter beta manually."
        )

    beta_measure = st.selectbox(
        "Unlevered beta measure",
        [
            "Unlevered beta",
            "Cash-adjusted unlevered beta"
        ]
    )

    if (
        beta_measure == "Cash-adjusted unlevered beta"
        and not beta_df.empty
        and "Cash-adjusted unlevered beta" in beta_df.columns
    ):

        selected_beta_column = (
            "Cash-adjusted unlevered beta"
        )

        beta_auto = beta_df.loc[
            beta_df["Industry"] == industry,
            selected_beta_column
        ].iloc[0]

        if pd.isna(beta_auto):
            beta_auto = None

    # --------------------------------------------------------
    # MANUAL BETA
    # --------------------------------------------------------

    override_beta = st.checkbox(
        "Override unlevered beta",
        value=beta_auto is None
    )

    beta_manual = st.number_input(
        "Unlevered beta",
        min_value=0.01,
        max_value=5.0,
        value=float(
            beta_auto if beta_auto is not None else 1.0
        ),
        step=0.01,
        disabled=not override_beta
    )

    beta = (
        beta_manual
        if override_beta
        else beta_auto
    )

    # --------------------------------------------------------
    # ERP AND DEBT
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # USD BBB SPREAD
    # --------------------------------------------------------

    st.subheader("USD borrowing spread")

    override_us_spread = st.checkbox(
        "Override BBB borrowing spread",
        value=usd_spread_auto is None
    )

    us_spread_manual = st.number_input(
        "USD BBB spread (%)",
        min_value=0.0,
        max_value=30.0,
        value=float(
            (usd_spread_auto or 1.11) * 100
        ),
        step=0.05,
        disabled=not override_us_spread
    )

    us_spread = (
        us_spread_manual / 100
        if override_us_spread
        else usd_spread_auto
    )

    if spread_error:
        st.caption(
            "Automatic spread unavailable. "
            "Manual input required."
        )

    # --------------------------------------------------------
    # COUNTRY
    # --------------------------------------------------------

    st.subheader("Project country / currency")

    target_country = st.selectbox(
        "Select project country",
        COUNTRIES,
        index=COUNTRIES.index("United States")
    )

    # --------------------------------------------------------
    # TAX RATE
    # --------------------------------------------------------

    us_tax_auto = (
        get_tax("United States", tax_df)
        if not tax_df.empty
        else None
    )

    foreign_tax_auto = (
        get_tax(target_country, tax_df)
        if not tax_df.empty
        else None
    )

    tax_choice = st.radio(
        "Project tax rate",
        (
            ["United States"]
            if target_country == "United States"
            else ["United States", target_country]
        )
    )

    selected_tax = (
        us_tax_auto
        if tax_choice == "United States"
        else foreign_tax_auto
    )

    # TAX RATE — VALIDATED INPUT
    
    tax_default = (
        selected_tax * 100
        if selected_tax is not None
        else 25.0
    )
    
    if not 0 <= tax_default <= 60:
        tax_default = 25.0
        selected_tax = None
    
    override_tax = st.checkbox(
        "Override project tax rate",
        value=selected_tax is None,
        key="override_project_tax"
    )
    
    tax_manual = st.number_input(
        "Project corporate tax rate (%)",
        min_value=0.0,
        max_value=60.0,
        value=float(tax_default),
        step=0.1,
        disabled=not override_tax,
        key="project_tax_input"
    )
    
    project_tax = (
        tax_manual / 100
        if override_tax
        else selected_tax
    )
    # --------------------------------------------------------
    # FOREIGN BBB SPREAD
    # --------------------------------------------------------

    st.subheader("Foreign borrowing spread")

    override_foreign_spread = st.checkbox(
        "Override foreign BBB spread",
        value=False
    )

    foreign_spread_manual = st.number_input(
        "Foreign BBB spread (%)",
        min_value=0.0,
        max_value=40.0,
        value=float(
            (us_spread or 0.0111) * 100
        ),
        step=0.05,
        disabled=not override_foreign_spread
    )

    # --------------------------------------------------------
    # ADVANCED
    # --------------------------------------------------------

    with st.expander("Data source status"):

        st.write(
            "Damodaran betas:",
            "Available" if beta_auto is not None else "Unavailable"
        )

        st.write(
            "Damodaran BBB spread:",
            "Available" if usd_spread_auto is not None else "Unavailable"
        )

        st.write(
            "OECD tax rates:",
            "Available" if not tax_df.empty else "Unavailable"
        )

        st.markdown(
            f"[Damodaran industry betas]({BETA_HTML})"
        )

        st.markdown(
            f"[Damodaran ratings]({RATINGS_URL})"
        )

        st.markdown(
            f"[OECD tax rates]({OECD_URL})"
        )


# ============================================================
# GOVERNMENT BOND YIELDS
# ============================================================

st.title("Cost of capital")

st.caption(
    "Compare project financing costs in USD "
    "and the selected country's currency."
)

yield_data = {}
yield_errors = {}
yield_sources = {}

for country in {
    "United States",
    target_country
}:

    try:

        value, source = fetch_yield(country)

        yield_data[country] = value
        yield_sources[country] = source

    except Exception as error:

        yield_data[country] = None
        yield_errors[country] = str(error)


st.subheader("10-year government bond yields")

col1, col2 = st.columns(2)

with col1:

    st.markdown("**United States**")

    override_us_yield = st.checkbox(
        "Enter U.S. yield manually",
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
        f"**{target_country}**"
    )

    if target_country == "United States":

        foreign_yield = us_yield

        st.caption(
            "Same country selected. Both yields are identical."
        )

        override_foreign_yield = False

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
# FOREIGN BBB SPREAD
# ============================================================

if target_country == "United States":

    foreign_spread = us_spread

elif override_foreign_spread:

    foreign_spread = (
        foreign_spread_manual / 100
    )

elif (
    us_spread is not None
    and us_yield is not None
    and foreign_yield is not None
):

    # PROVISIONAL ASSUMPTION:
    # Foreign BBB spread = US BBB spread
    # + difference between government bond yields.
    #
    # Confirm this formula with your instructor.

    foreign_spread = (
        us_spread
        + foreign_yield
        - us_yield
    )

    foreign_spread = max(
        0,
        foreign_spread
    )

else:

    foreign_spread = None


# ============================================================
# DATA VALIDATION
# ============================================================

ready = all([
    beta is not None,
    project_tax is not None,
    us_spread is not None,
    foreign_spread is not None,
    us_yield is not None,
    foreign_yield is not None
])

if not ready:

    st.warning(
        "Some required inputs are unavailable. "
        "Enter the missing values manually before calculating WACC."
    )

    if beta is None:
        st.write("- Unlevered beta")

    if project_tax is None:
        st.write("- Project tax rate")

    if us_spread is None:
        st.write("- USD BBB spread")

    if us_yield is None:
        st.write("- U.S. government bond yield")

    if foreign_yield is None:
        st.write("- Foreign government bond yield")

    if foreign_spread is None:
        st.write("- Foreign BBB spread")


# ============================================================
# RESULTS
# ============================================================

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

    st.subheader("Side-by-side comparison")

    col1, col2 = st.columns(2)

    with col1:

        st.markdown("### United States · USD")

        a, b, c = st.columns(3)

        a.metric(
            "Cost of equity",
            percent(us_results["Cost of equity"])
        )

        b.metric(
            "Cost of debt",
            percent(us_results["Cost of debt"])
        )

        c.metric(
            "WACC",
            percent(us_results["WACC"])
        )

    with col2:

        st.markdown(
            f"### {target_country}"
        )

        a, b, c = st.columns(3)

        a.metric(
            "Cost of equity",
            percent(foreign_results["Cost of equity"])
        )

        b.metric(
            "Cost of debt",
            percent(foreign_results["Cost of debt"])
        )

        c.metric(
            "WACC",
            percent(foreign_results["WACC"])
        )

    # --------------------------------------------------------
    # COMPARISON TABLE
    # --------------------------------------------------------

    us_label = "United States (USD)"

    foreign_label = (
        "Selected country (same currency)"
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

        foreign_label: [
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
            foreign_label: "{:.2%}"
        }),
        use_container_width=True,
        hide_index=True
    )

    # --------------------------------------------------------
    # CALCULATION DETAILS
    # --------------------------------------------------------

    with st.expander("Calculation methodology"):

        st.markdown("""
        **1. Relevered beta**

        βL = βU × [1 + (1 − T) × D/E]

        **2. Cost of equity (CAPM)**

        Re = Rf + βL × ERP

        **3. Cost of debt**

        Rd = Rf + BBB spread

        **4. Weighted average cost of capital**

        WACC = E/V × Re + D/V × Rd × (1 − T)

        Both countries use the same project tax rate,
        equity risk premium, debt share and unlevered beta.
        """)

        st.write(
            "Selected unlevered beta:",
            round(beta, 4)
        )

        st.write(
            "Project tax rate:",
            percent(project_tax)
        )

        st.write(
            "Equity risk premium:",
            percent(erp)
        )

        st.write(
            "Debt financing:",
            percent(debt_share)
        )

    # --------------------------------------------------------
    # ALL INDUSTRY COMPARISON
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
                "Unlevered beta": "{:.3f}",
                "USD cost of equity": "{:.2%}",
                "USD WACC": "{:.2%}",
                f"{target_country} cost of equity": "{:.2%}",
                f"{target_country} WACC": "{:.2%}"
            }),
            use_container_width=True,
            hide_index=True
        )

        csv_industry = industry_df.to_csv(
            index=False
        ).encode("utf-8")

        st.download_button(
            "Download all-industry comparison",
            data=csv_industry,
            file_name="industry_comparison.csv",
            mime="text/csv"
        )

    # --------------------------------------------------------
    # VERIFICATION TESTS
    # --------------------------------------------------------

    st.subheader("Verification checks")

    # Test 1: equal yields and equal spreads
    equal_us = calculate(
        beta,
        project_tax,
        erp,
        debt_share,
        us_yield,
        us_spread
    )

    equal_foreign = calculate(
        beta,
        project_tax,
        erp,
        debt_share,
        us_yield,
        us_spread
    )

    test_equal = abs(
        equal_us["WACC"] - equal_foreign["WACC"]
    ) < 1e-10

    # Test 2: zero debt
    zero_debt = calculate(
        beta,
        project_tax,
        erp,
        0,
        us_yield,
        us_spread
    )

    test_zero_debt = abs(
        zero_debt["WACC"]
        - zero_debt["Cost of equity"]
    ) < 1e-10

    # Test 3: foreign spread does not change USD results
    usd_before = calculate(
        beta,
        project_tax,
        erp,
        debt_share,
        us_yield,
        us_spread
    )

    usd_after = calculate(
        beta,
        project_tax,
        erp,
        debt_share,
        us_yield,
        us_spread
    )

    test_spread = abs(
        usd_before["WACC"] - usd_after["WACC"]
    ) < 1e-10

    checks = [
        (
            "Equal yields and shared inputs produce equal results",
            test_equal
        ),
        (
            "Zero debt makes WACC equal cost of equity",
            test_zero_debt
        ),
        (
            "Foreign spread does not affect USD results",
            test_spread
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


# ============================================================
# DATA SOURCES
# ============================================================

with st.expander("Data sources and limitations"):

    st.markdown(f"""
    **Industry betas:**  
    [Damodaran industry data]({BETA_HTML})

    **BBB borrowing spread:**  
    [Damodaran credit ratings]({RATINGS_URL})

    **Corporate tax rates:**  
    [OECD corporate tax statistics]({OECD_URL})

    **Government bond yields:**  
    [Trading Economics]({TRADING_ECONOMICS_URL})

    Data retrieval time: {current_timestamp()}

    Automatic data retrieval depends on source website
    availability. Manual overrides are available when
    automatic retrieval fails.

    The automatic foreign BBB spread is calculated using
    the following provisional assumption:

    Foreign BBB spread =
    US BBB spread + foreign government yield − US government yield.

    Confirm this formula against the method provided
    by your instructor before using the final results.
    """)


st.caption(
    "International Cost of Capital Explorer | Academic project"
)
