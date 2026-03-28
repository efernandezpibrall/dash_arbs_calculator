"""
UFC Calculator Dashboard - Main Page

This page displays UFC calculation results in a format matching the
ufc_calculator_visualization.png reference image.
"""

import os
import sys
import configparser
import pandas as pd
from datetime import date, datetime
from dateutil.relativedelta import relativedelta
from sqlalchemy import create_engine, text
from dash import html, dcc, callback, Output, Input
import dash_bootstrap_components as dbc

# Import UFC calculation functions
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from fundamentals.arbs_calculator.ufc_calculations import (
    calculate_laden_leg,
    calculate_ballast_leg,
    calculate_voyage_ufc
)
from fundamentals.arbs_calculator.data_loaders import (
    fetch_port_cost,
    fetch_latest_lng_price,
    fetch_hire_rate,
    fetch_eua_price
)
from fundamentals.arbs_calculator.emissions_calculator import calculate_ets_cost

# =====================================================
# Database Configuration
# =====================================================

# Load config file with path resolution
try:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_dir = os.path.abspath(os.path.join(script_dir, '..', '..'))
    CONFIG_FILE_PATH = os.path.join(config_dir, 'config.ini')
except:
    CONFIG_FILE_PATH = 'config.ini'

config_reader = configparser.ConfigParser(interpolation=None)
config_reader.read(CONFIG_FILE_PATH)

DB_CONNECTION_STRING = config_reader.get('DATABASE', 'CONNECTION_STRING', fallback=None)

if not DB_CONNECTION_STRING:
    raise ValueError(f"Missing DATABASE CONNECTION_STRING in {CONFIG_FILE_PATH}")

# Create database engine
engine = create_engine(DB_CONNECTION_STRING, pool_pre_ping=True)

# =====================================================
# Data Fetching Functions
# =====================================================

def fetch_route_list():
    """Get all active routes from uploader_shipping_routes_inputs."""
    query = """
        SELECT route_name
        FROM at_lng.uploader_shipping_routes_inputs
        WHERE active = TRUE
        ORDER BY route_name
    """
    try:
        df = pd.read_sql(query, engine)
        return df['route_name'].tolist()
    except Exception as e:
        print(f"Error fetching route list: {e}")
        return []


def generate_delivery_months(months_back=3, months_forward=12):
    """
    Generate a list of delivery months in MM-YYYY format.

    Args:
        months_back: Number of months to go back from current month
        months_forward: Number of months to go forward from current month

    Returns:
        List of dicts with 'label' and 'value' keys for dropdown options
    """
    today = datetime.today()
    current_month = today.replace(day=1)

    months = []
    for i in range(-months_back, months_forward + 1):
        month_date = current_month + relativedelta(months=i)
        month_str = month_date.strftime('%m-%Y')
        month_label = month_date.strftime('%b %Y')
        months.append({'label': month_label, 'value': month_str})

    return months


def calculate_ufc_live(route_name, calculation_date=None):
    """
    Calculate UFC live using route configuration and current market data.

    Args:
        route_name: Name of the route to calculate
        calculation_date: Optional date for calculation (defaults to today)

    Returns:
        Dictionary with calculation results (same structure as database table)
    """
    # Get route configuration
    config_df = fetch_route_config(route_name)
    if config_df.empty:
        raise ValueError(f"Route not found: {route_name}")

    route = config_df.iloc[0]

    # Convert calculation_date to string format if it's a date object
    if calculation_date is None:
        calc_date = str(date.today())
    elif isinstance(calculation_date, date):
        calc_date = str(calculation_date)
    else:
        calc_date = calculation_date

    # Determine vessel type from vessel size
    vessel_size = route['vessel_size_cbm']
    if vessel_size <= 150000:
        vessel_type = '145k_steam'
    elif vessel_size <= 165000:
        vessel_type = '160k_tfde'
    elif vessel_size <= 180000:
        vessel_type = '174k_megi'
    elif vessel_size <= 210000:
        vessel_type = 'qflex'
    else:
        vessel_type = 'qmax'

    # Fetch port costs
    load_port_cost = fetch_port_cost(
        engine,
        route['load_port_name'],
        vessel_type
    )

    discharge_port_cost = fetch_port_cost(
        engine,
        route['discharge_port_name'],
        vessel_type
    )

    # Fetch LNG price (region-aware)
    lng_price_mmbtu = fetch_latest_lng_price(
        engine,
        region=route['region'],
        calculation_date=calc_date
    )

    # Convert $/mmbtu to $/mt using route-specific CF
    cf = route.get('conversion_factor', 52.53)
    foe = route.get('foe', 0.484)
    lng_price_mt = lng_price_mmbtu * (cf / foe)

    # Fetch hire rate from uploader_shipping_curves based on region
    hire_usd_day = fetch_hire_rate(
        engine=engine,
        region=route['region'],
        calculation_date=calc_date
    )

    # Fetch EUA price dynamically (month-specific contract)
    eua_price_eur = fetch_eua_price(
        engine=engine,
        calculation_date=calc_date
    )

    # EUR/USD FX rate (hardcoded for now - no data source available)
    eur_usd_fx = 1.10  # Default EUR/USD FX

    # Calculate ETS costs if EU ports are involved
    ets_cost_laden = 0
    ets_cost_ballast = 0

    if route.get('laden_eu_port', False) or route.get('discharge_eu_port', False):
        laden_lng_mt = route['voyage_consumption_mt_day'] * route['laden_days']
        ballast_lng_mt = route['voyage_consumption_mt_day'] * route['ballast_days']

        ets_result = calculate_ets_cost(
            laden_lng_mt=laden_lng_mt,
            ballast_lng_mt=ballast_lng_mt,
            eua_price_eur=eua_price_eur,
            eur_usd_fx=eur_usd_fx,
            engine_type=route['engine_type'],
            laden_eu_port=route['laden_eu_port'],
            discharge_eu_port=route['discharge_eu_port']
        )
        ets_cost_laden = ets_result['ets_cost_usd']
        ets_cost_ballast = 0  # ETS is allocated to laden leg only

    # Calculate laden leg
    laden_results = calculate_laden_leg(
        vessel_size_cbm=route['vessel_size_cbm'],
        load_volume_pct=route['load_volume_percent'],
        conversion_factor=cf,
        laden_days=int(route['laden_days']),
        hire_usd_day=hire_usd_day,
        voy_cons_mt_day=route['voyage_consumption_mt_day'],
        nbor_rate=route['nbor_rate'],
        lng_price_usd_mt=lng_price_mt,
        load_port_cost_usd=load_port_cost,
        discharge_port_cost_usd=discharge_port_cost,
        foe=foe,
        awrp_usd=route.get('awrp_laden_usd', 0),
        canal_cost_usd=route['canal_cost_usd'] if (route.get('laden_suez_transit', False) or route.get('laden_panama_transit', False)) else 0,
        ets_cost_laden_usd=ets_cost_laden,
        heel_cbm=route.get('heel_cbm', None)
    )

    # Calculate ballast leg
    ballast_results = calculate_ballast_leg(
        ballast_days=int(route['ballast_days']),
        hire_usd_day=hire_usd_day,
        voy_cons_mt_day=route['voyage_consumption_mt_day'],
        lng_price_usd_mt=lng_price_mt,
        load_port_cost_usd=load_port_cost,
        awrp_usd=route.get('awrp_ballast_usd', 0),
        canal_cost_usd=0,  # Canal cost only applies to laden leg
        ets_cost_ballast_usd=ets_cost_ballast
    )

    # Calculate voyage UFC
    ufc_results = calculate_voyage_ufc(
        laden_results,
        ballast_results,
        int(route['laden_days']),
        int(route['ballast_days'])
    )

    # Combine all results into a dictionary matching database structure
    return {
        'route_name': route_name,
        'calculation_date': calc_date,
        'vessel_size_cbm': route['vessel_size_cbm'],
        'load_volume_pct': route['load_volume_percent'],
        'conversion_factor': cf,
        'foe': foe,
        'laden_days': route['laden_days'],
        'ballast_days': route['ballast_days'],
        'hire_usd_day': hire_usd_day,
        'lng_price_usd_mt': lng_price_mt,
        'load_port_name': route['load_port_name'],
        'discharge_port_name': route['discharge_port_name'],
        'eua_price_eur': eua_price_eur,
        'eur_usd_fx': eur_usd_fx,

        # Laden leg results
        'fob_volume_cbm': laden_results['fob_volume_cbm'],
        'fob_volume_mmbtu': laden_results['fob_volume_mmbtu'],
        'des_volume_cbm': laden_results['des_volume_cbm'],
        'des_volume_mmbtu': laden_results['des_volume_mmbtu'],
        'laden_bog_fuel_mt': laden_results['bog_fuel_mt'],
        'laden_bog_fuel_cost_usd': laden_results['bog_fuel_cost_usd'],
        'laden_hire_cost_usd': laden_results['hire_cost_usd'],
        'laden_port_costs_usd': laden_results['port_costs_usd'],
        'laden_awrp_usd': laden_results['awrp_usd'],
        'laden_canal_cost_usd': laden_results['canal_cost_usd'],
        'laden_ets_cost_usd': laden_results['ets_cost_usd'],
        'laden_total_cost_usd': laden_results['total_cost_usd'],

        # Ballast leg results
        'ballast_bog_fuel_mt': ballast_results['bog_fuel_mt'],
        'ballast_bog_fuel_cost_usd': ballast_results['bog_fuel_cost_usd'],
        'ballast_hire_cost_usd': ballast_results['hire_cost_usd'],
        'ballast_port_cost_usd': ballast_results['port_cost_usd'],
        'ballast_awrp_usd': ballast_results['awrp_usd'],
        'ballast_canal_cost_usd': ballast_results['canal_cost_usd'],
        'ballast_ets_cost_usd': ballast_results['ets_cost_usd'],
        'ballast_total_cost_usd': ballast_results['total_cost_usd'],

        # Voyage UFC results
        'voy_days': ufc_results['voy_days'],
        'voy_costs_usd': ufc_results['voy_costs_usd'],
        'voy_ufc_usd_mmbtu': ufc_results['voy_ufc_usd_mmbtu'],
        'daily_ufc_usd_day': ufc_results['daily_ufc_usd_day']
    }


def fetch_route_config(route_name):
    """Get route configuration details."""
    query = text("""
        SELECT *
        FROM at_lng.uploader_shipping_routes_inputs
        WHERE route_name = :route_name
    """)

    try:
        with engine.connect() as conn:
            result = pd.read_sql(query, conn, params={'route_name': route_name})
        return result
    except Exception as e:
        print(f"Error fetching route config: {e}")
        return pd.DataFrame()


# =====================================================
# Navigation Bar
# =====================================================

navbar = dbc.NavbarSimple(
    children=[
        dbc.NavItem(dbc.NavLink("UFC Calculator", href="/", active=True)),
        dbc.NavItem(dbc.NavLink("Port Costs", href="/port-costs")),
    ],
    brand="UFC Calculator Dashboard",
    brand_href="/",
    color="primary",
    dark=True,
    className="mb-3",
    fluid=True
)

# =====================================================
# Layout Components
# =====================================================

layout = html.Div([
    navbar,

    # Header with controls
    html.Div([
        html.H1("UFC Calculator Dashboard", style={
            'color': '#2E86C1',
            'margin': '0',
            'padding': '8px 0 4px 0',
            'font-size': '18px'
        }),
        html.Div([
            dcc.Dropdown(
                id='route-dropdown',
                value='USG-GATE',
                placeholder='Select Route',
                persistence=True,
                persistence_type='session',
                style={'width': '350px', 'margin-right': '20px'}
            ),
            dcc.Dropdown(
                id='delivery-month-dropdown',
                options=generate_delivery_months(months_back=3, months_forward=12),
                value=datetime.today().strftime('%m-%Y'),
                placeholder='Select Delivery Month',
                persistence=True,
                persistence_type='session',
                style={'width': '200px', 'margin-right': '20px'}
            ),
            html.Button('Refresh', id='refresh-button', className='btn-refresh',
                       style={'margin-left': '20px', 'padding': '4px 12px', 'font-size': '12px'})
        ], style={
            'display': 'flex',
            'align-items': 'center',
            'margin-top': '10px'
        })
    ], style={
        'padding': '8px 12px',
        'background-color': '#f8f9fa',
        'border-bottom': '2px solid #2E86C1'
    }),

    # Container for route header and columns
    html.Div([
        # Route header row (spans both columns)
        html.Div(id='route-header', style={
            'padding': '6px 12px',
            'background-color': '#1a5a8a',
            'color': 'white',
            'font-size': '13px',
            'font-weight': 'bold',
            'text-align': 'center',
            'border-radius': '4px 4px 0 0',
            'margin-bottom': '0'
        }),

        # Main content area - 2 columns
        html.Div([
            # LEFT COLUMN
            html.Div([
            # Charter subsection
            html.Div(id='charter-section', style={'padding': '8px', 'font-size': '13px'}),

            # Charter $$$ subsection
            html.Div(id='charter-summary-section', style={'padding': '8px', 'font-size': '13px', 'margin-top': '2px'}),

            # Charter Costs subsection
            html.Div(id='charter-costs-section', style={'padding': '8px', 'font-size': '13px', 'margin-top': '2px'}),

            # Summary TCE subsection
            html.Div(id='summary-tce-section', style={'padding': '8px', 'font-size': '13px', 'margin-top': '2px'})
        ], style={
            'flex': '0 0 auto',
            'min-width': '350px',
            'max-width': '350px',
            'border': '1px solid #ddd',
            'padding': '8px',
            'margin-right': '0px',
            'background-color': 'white'
        }),

        # RIGHT COLUMN
        html.Div([
            # Market Prices & CF subsection
            html.Div(id='market-prices-section', style={'padding': '8px', 'font-size': '13px'}),

            # Laden Voy subsection
            html.Div(id='laden-voy-section', style={'padding': '8px', 'font-size': '13px', 'margin-top': '2px'}),

            # Ballast Voy subsection
            html.Div(id='ballast-voy-section', style={'padding': '8px', 'font-size': '13px', 'margin-top': '2px'}),

            # Summary subsection
            html.Div(id='summary-section', style={'padding': '8px', 'font-size': '13px', 'margin-top': '2px'})
        ], style={
            'flex': '0 0 auto',
            'min-width': '350px',
            'max-width': '350px',
            'border': '1px solid #ddd',
            'padding': '8px',
            'margin-left': '0px',
            'background-color': 'white'
        })
        ], style={'display': 'flex', 'padding': '0 10px 10px 10px'})
    ], style={'padding': '10px 0', 'max-width': 'fit-content', 'margin': '0 auto'}),

    # Footnote at the bottom of the page
    html.Div([
        html.Div([
            html.Span("* ", style={'font-size': '10px', 'color': '#6b7280'}),
            html.Span("BOG/Fuel calculated as max of (Size × NBOG × Laden Days) and (Laden Days × Voy Cons). ",
                     style={'font-size': '10px', 'color': '#6b7280', 'font-style': 'italic', 'line-height': '1.3'}),
            html.Span("Example: For a 174,000 m³ vessel with 0.10% NBOG over 15 laden days, BOG = max[(174,000 × 0.001 × 15) = 2,610 m³, (15 × 150 mt/day) / FOE] = 2,610 m³.",
                     style={'font-size': '9px', 'color': '#9ca3af', 'font-style': 'italic', 'line-height': '1.3'})
        ], style={'margin-bottom': '6px'}),
        html.Div([
            html.Span("** ", style={'font-size': '10px', 'color': '#6b7280'}),
            html.Span("ETS costs calculated based on CO₂ emissions from fuel consumption, engine type efficiency, EUA carbon price (€/tonne CO₂), and EUR/USD FX rate. ETS applies only when EU ports are involved and is allocated to the laden leg. ",
                     style={'font-size': '10px', 'color': '#6b7280', 'font-style': 'italic', 'line-height': '1.3'}),
            html.Span("Example: 2,000 mt LNG fuel × 2.75 tCO₂/mt × €80/tCO₂ × 1.10 EUR/USD = $484,000 ETS cost.",
                     style={'font-size': '9px', 'color': '#9ca3af', 'font-style': 'italic', 'line-height': '1.3'})
        ])
    ], style={
        'padding': '8px 20px',
        'margin-top': '0px',
        'border-top': '1px solid #e5e7eb',
        'background-color': '#f8f9fa'
    })
])


# =====================================================
# Callbacks
# =====================================================

# Callback 1: Populate dropdown options
@callback(
    Output('route-dropdown', 'options'),
    Input('refresh-button', 'n_clicks'),
    prevent_initial_call=False
)
def populate_route_options(n_clicks):
    """Populate dropdown with available routes."""
    routes = fetch_route_list()
    return [{'label': r, 'value': r} for r in routes]


# Callback 2: Update dashboard based on route selection
@callback(
    Output('route-header', 'children'),
    Output('charter-section', 'children'),
    Output('laden-voy-section', 'children'),
    Output('ballast-voy-section', 'children'),
    Output('market-prices-section', 'children'),
    Output('charter-summary-section', 'children'),
    Output('charter-costs-section', 'children'),
    Output('summary-tce-section', 'children'),
    Output('summary-section', 'children'),
    Input('refresh-button', 'n_clicks'),
    Input('route-dropdown', 'value'),
    Input('delivery-month-dropdown', 'value'),
    prevent_initial_call=False
)
def update_dashboard(n_clicks, route_name, delivery_month):
    """Update all dashboard sections based on route and delivery month selection."""

    print(f"DEBUG: Callback triggered with route_name='{route_name}', delivery_month='{delivery_month}'")

    # Default to USG-GATE if no route selected
    if route_name is None:
        route_name = 'USG-GATE'

    # Convert delivery month (MM-YYYY) to date for the 15th of that month
    # This will be used for fetching market prices
    calculation_date = None
    if delivery_month:
        try:
            month, year = delivery_month.split('-')
            calculation_date = datetime(int(year), int(month), 15).date()
        except:
            calculation_date = None

    # Calculate UFC live + fetch route config
    try:
        calc = calculate_ufc_live(route_name, calculation_date)
        config_df = fetch_route_config(route_name)

        if config_df.empty:
            raise ValueError(f"Route config not found: {route_name}")

        config = config_df.iloc[0]

    except Exception as e:
        error_msg = html.Div([
            html.P(f"Error calculating UFC: {str(e)}",
                  style={'color': '#dc3545', 'font-weight': 'bold'}),
            html.P("Check route configuration and market data availability.",
                  style={'color': '#6b7280', 'font-size': '12px'})
        ])
        return "Error", error_msg, "", "", "", "", "", "", ""

    # Build Charter section
    charter_content = html.Div([
        html.H5("Charter", style={
            'background-color': '#2E86C1',
            'color': 'white',
            'padding': '6px',
            'margin': '-8px -8px 4px -8px',
            'font-size': '12px'
        }),
        html.Div([html.Strong("Vessel: "), f"{config['vessel_size_cbm']:,.0f} cbm"],
                style={'margin-bottom': '0', 'line-height': '1.2'}),
        html.Div([html.Strong("Size: "), f"{config['vessel_size_cbm']:,.0f} m³"],
                style={'margin-bottom': '0', 'line-height': '1.2'}),
        html.Div([html.Strong("Load Volume: "), f"{config['load_volume_percent']:.2f}% | {config['vessel_size_cbm'] * (config['load_volume_percent'] / 100):,.0f} m³"],
                style={'margin-bottom': '0', 'line-height': '1.2'}),
        html.Div([html.Strong("Heel: "), f"{config['heel_cbm']:,.0f} m³"],
                style={'margin-bottom': '0', 'line-height': '1.2'}),
        html.Div([html.Strong("Voy Cons: "), f"{config['voyage_consumption_mt_day']:.0f} mt/day"],
                style={'margin-bottom': '0', 'line-height': '1.2'}),
        html.Div([html.Strong("NBOG: "), f"{config['nbor_rate']*100:.2f}%"],
                style={'margin-bottom': '0', 'line-height': '1.2'}),
        html.Div([html.Strong("FOE: "), f"{config['foe']} mt/m³"],
                style={'margin-bottom': '0', 'line-height': '1.2'}),
        html.Div([html.Strong("CF: "), f"{config['conversion_factor']} mmbtu/m³"],
                style={'margin-bottom': '0', 'line-height': '1.2'}),
        html.Div([html.Strong("Hire: "), f"${calc['hire_usd_day']:,.0f}/day"],
                style={'margin-bottom': '0', 'line-height': '1.2'},
                title=f"Hire Rate: ${calc['hire_usd_day']:,.0f}/day (Source: uploader_shipping_curves for region '{config['region']}')"),
        html.Hr(style={'margin': '0', 'border-color': '#555'}),
        html.Div([html.Strong("Laden Days: "), f"{config['laden_days']} days"],
                style={'margin-bottom': '0', 'line-height': '1.2'}),
        html.Div([html.Strong("Ballast Days: "), f"{config['ballast_days']} days"],
                style={'margin-bottom': '0', 'line-height': '1.2'}),
        html.Div([html.Strong("Voy Days: "), f"{calc['voy_days']} days"],
                style={'margin-bottom': '0', 'line-height': '1.2'},
                title=f"Voyage Days: Laden Days {config['laden_days']} + Ballast Days {config['ballast_days']} = {calc['voy_days']} days"),
    ])

    # Calculate LNG price in $/mmbtu from $/mt
    lng_price_mmbtu = calc['lng_price_usd_mt'] / (config['conversion_factor'] / config['foe'])

    # Build Market Prices section
    market_prices_content = html.Div([
        html.H5("Market Prices", style={
            'background-color': '#2E86C1',
            'color': 'white',
            'padding': '6px',
            'margin': '-8px -8px 4px -8px',
            'font-size': '12px'
        }),
        html.Div([html.Strong("LNG Price: "), f"{lng_price_mmbtu:.2f} $/mmbtu | {calc['lng_price_usd_mt']:.2f} $/mt"],
                style={'margin-bottom': '0', 'line-height': '1.2'},
                title=f"LNG Price ($/mmbtu): ${calc['lng_price_usd_mt']:.2f}/mt / (CF {config['conversion_factor']} / FOE {config['foe']}) = ${lng_price_mmbtu:.2f}/mmbtu"),
        html.Div([html.Strong("EUA Price: "), f"€{calc['eua_price_eur']:.2f}/tonne | ${calc['eua_price_eur'] * calc['eur_usd_fx']:.2f}/tonne"],
                style={'margin-bottom': '0', 'line-height': '1.2'},
                title=f"EUA Price ($/tonne): €{calc['eua_price_eur']:.2f}/tonne × EUR/USD {calc['eur_usd_fx']:.4f} = ${calc['eua_price_eur'] * calc['eur_usd_fx']:.2f}/tonne"),
        html.Div([html.Strong("EUR/USD: "), f"{calc['eur_usd_fx']:.4f}"],
                style={'margin-bottom': '0', 'line-height': '1.2'}),
    ])

    # Build Laden Voy section
    laden_voy_content = html.Div([
        html.H5("Laden Voy", style={
            'background-color': '#2E86C1',
            'color': 'white',
            'padding': '6px',
            'margin': '-8px -8px 4px -8px',
            'font-size': '12px'
        }),
        html.Div([html.Strong("FOB Volume: "), f"{calc['fob_volume_cbm']:,.0f} m³ | {calc['fob_volume_mmbtu']:,.0f} mmbtu"],
                style={'margin-bottom': '0', 'line-height': '1.2'},
                title=f"FOB Volume (mmbtu): {calc['fob_volume_cbm']:,.0f} m³ × CF {config['conversion_factor']} mmbtu/m³ = {calc['fob_volume_mmbtu']:,.0f} mmbtu"),
        html.Div([html.Strong("BOG/Fuel: "), f"{calc['laden_bog_fuel_mt'] / config['foe']:,.0f} m³ | {calc['laden_bog_fuel_mt']:,.0f} mt | {calc['laden_bog_fuel_mt'] * (config['conversion_factor'] / config['foe']):,.0f} mmbtu"],
                style={'margin-bottom': '0', 'line-height': '1.2'},
                title=f"BOG/Fuel: max[(Size {config['vessel_size_cbm']:,.0f} m³ × NBOG {config['nbor_rate']*100:.2f}% × Laden Days {config['laden_days']}) = {config['laden_days'] * (config['vessel_size_cbm'] * config['nbor_rate']) * config['foe']:,.0f} mt, (Laden Days {config['laden_days']} × Voy Cons {config['voyage_consumption_mt_day']:.0f} mt/day) = {config['laden_days'] * config['voyage_consumption_mt_day']:,.0f} mt] = {calc['laden_bog_fuel_mt']:,.0f} mt | Convert: {calc['laden_bog_fuel_mt']:,.0f} mt / FOE {config['foe']} = {calc['laden_bog_fuel_mt'] / config['foe']:,.0f} m³ | {calc['laden_bog_fuel_mt']:,.0f} mt × (CF {config['conversion_factor']} / FOE {config['foe']}) = {calc['laden_bog_fuel_mt'] * (config['conversion_factor'] / config['foe']):,.0f} mmbtu"),
        html.Div([html.Strong("DES Volume: "), f"{calc['des_volume_cbm']:,.0f} m³ | {calc['des_volume_mmbtu']:,.0f} mmbtu"],
                style={'margin-bottom': '0', 'line-height': '1.2'},
                title=f"DES Volume (m³): FOB Volume {calc['fob_volume_cbm']:,.0f} m³ - Heel {config['heel_cbm']:,.0f} m³ - BOG/Fuel {calc['laden_bog_fuel_mt'] / config['foe']:,.0f} m³ = {calc['des_volume_cbm']:,.0f} m³ | {calc['des_volume_mmbtu']:,.0f} mmbtu"),
        html.Hr(style={'margin': '0', 'border-color': '#555'}),
        html.Div([html.Strong("BOG/Fuel: "), f"${calc['laden_bog_fuel_cost_usd']:,.0f}"],
                style={'margin-bottom': '0', 'line-height': '1.2'},
                title=f"BOG/Fuel Cost: {calc['laden_bog_fuel_mt']:,.0f} mt × LNG Price ${calc['lng_price_usd_mt']:.2f}/mt = ${calc['laden_bog_fuel_cost_usd']:,.0f}"),
        html.Div([html.Strong("Hire: "), f"${calc['laden_hire_cost_usd']:,.0f}"],
                style={'margin-bottom': '0', 'line-height': '1.2'},
                title=f"Laden Hire: Hire Rate ${calc['hire_usd_day']:,.0f}/day × Laden Days {config['laden_days']} = ${calc['laden_hire_cost_usd']:,.0f}"),
        html.Div([html.Strong("Port Costs: "), f"${calc['laden_port_costs_usd']:,.0f}"],
                style={'margin-bottom': '0', 'line-height': '1.2'}),
        html.Div([html.Strong("AWRP: "), f"${calc['laden_awrp_usd']:,.0f}"],
                style={'margin-bottom': '0', 'line-height': '1.2'}),
        html.Div([html.Strong("Canal: "), f"${calc['laden_canal_cost_usd']:,.0f}"],
                style={'margin-bottom': '0', 'line-height': '1.2'}),
        html.Div([html.Strong("ETS: "), f"${calc['laden_ets_cost_usd']:,.0f}"],
                style={'margin-bottom': '0', 'line-height': '1.2'}),
        html.Div([html.Strong("Total: "), f"${calc['laden_total_cost_usd']:,.0f}"],
                style={'margin-bottom': '4px', 'font-weight': 'bold', 'background-color': '#e3f2fd', 'padding': '2px 4px'},
                title=f"Laden Total: BOG/Fuel ${calc['laden_bog_fuel_cost_usd']:,.0f} + Hire ${calc['laden_hire_cost_usd']:,.0f} + Port Costs ${calc['laden_port_costs_usd']:,.0f} + AWRP ${calc['laden_awrp_usd']:,.0f} + Canal ${calc['laden_canal_cost_usd']:,.0f} + ETS ${calc['laden_ets_cost_usd']:,.0f} = ${calc['laden_total_cost_usd']:,.0f}"),
    ])

    # Build Ballast Voy section
    # Calculate ballast fuel volume: Ballast Days × Voy Cons mt/day
    ballast_fuel_mt = config['ballast_days'] * config['voyage_consumption_mt_day']
    ballast_fuel_cbm = ballast_fuel_mt / config['foe']
    ballast_fuel_mmbtu = ballast_fuel_mt * (config['conversion_factor'] / config['foe'])

    ballast_voy_content = html.Div([
        html.H5("Ballast Voy", style={
            'background-color': '#2E86C1',
            'color': 'white',
            'padding': '6px',
            'margin': '-8px -8px 4px -8px',
            'font-size': '12px'
        }),
        html.Div([html.Strong("Fuel: "), f"{ballast_fuel_cbm:,.0f} m³ | {ballast_fuel_mt:,.0f} mt | {ballast_fuel_mmbtu:,.0f} mmbtu"],
                style={'margin-bottom': '0', 'line-height': '1.2'},
                title=f"Ballast Fuel: Ballast Days {config['ballast_days']} × Voy Cons {config['voyage_consumption_mt_day']:.0f} mt/day = {ballast_fuel_mt:,.0f} mt | Convert: {ballast_fuel_mt:,.0f} mt / FOE {config['foe']} = {ballast_fuel_cbm:,.0f} m³ | {ballast_fuel_mt:,.0f} mt × (CF {config['conversion_factor']} / FOE {config['foe']}) = {ballast_fuel_mmbtu:,.0f} mmbtu"),
        html.Hr(style={'margin': '0', 'border-color': '#555'}),
        html.Div([html.Strong("Fuel: "), f"${calc['ballast_bog_fuel_cost_usd']:,.0f}"],
                style={'margin-bottom': '0', 'line-height': '1.2'},
                title=f"Ballast Fuel Cost: {ballast_fuel_mt:,.0f} mt × LNG Price ${calc['lng_price_usd_mt']:.2f}/mt = ${calc['ballast_bog_fuel_cost_usd']:,.2f}"),
        html.Div([html.Strong("Hire: "), f"${calc['ballast_hire_cost_usd']:,.0f}"],
                style={'margin-bottom': '0', 'line-height': '1.2'},
                title=f"Ballast Hire: Hire Rate ${calc['hire_usd_day']:,.0f}/day × Ballast Days {config['ballast_days']} = ${calc['ballast_hire_cost_usd']:,.0f}"),
        html.Div([html.Strong("Port Costs: "), f"${calc['ballast_port_cost_usd']:,.0f}"],
                style={'margin-bottom': '0', 'line-height': '1.2'}),
        html.Div([html.Strong("AWRP: "), f"${calc['ballast_awrp_usd']:,.0f}"],
                style={'margin-bottom': '0', 'line-height': '1.2'}),
        html.Div([html.Strong("Canal: "), f"${calc['ballast_canal_cost_usd']:,.0f}"],
                style={'margin-bottom': '0', 'line-height': '1.2'}),
        html.Div([html.Strong("Total: "), f"${calc['ballast_total_cost_usd']:,.0f}"],
                style={'margin-bottom': '4px', 'font-weight': 'bold', 'background-color': '#e3f2fd', 'padding': '2px 4px'},
                title=f"Ballast Total: Fuel ${calc['ballast_bog_fuel_cost_usd']:,.2f} + Hire ${calc['ballast_hire_cost_usd']:,.0f} + Port Costs ${calc['ballast_port_cost_usd']:,.0f} + AWRP ${calc['ballast_awrp_usd']:,.0f} + Canal ${calc['ballast_canal_cost_usd']:,.0f} = ${calc['ballast_total_cost_usd']:,.0f}"),
    ])

    # Build NEW Charter $$$ section (Laden costs only)
    charter_summary_content = html.Div([
        html.H5("Charter $$$", style={
            'background-color': '#2E86C1',
            'color': 'white',
            'padding': '6px',
            'margin': '-8px -8px 4px -8px',
            'font-size': '12px'
        }),
        html.Div([html.Strong("Laden Hire: "), f"${calc['laden_hire_cost_usd']:,.0f}"],
                style={'margin-bottom': '0', 'line-height': '1.2'},
                title=f"Laden Hire: Hire Rate ${calc['hire_usd_day']:,.0f}/day × Laden Days {config['laden_days']} = ${calc['laden_hire_cost_usd']:,.0f}"),
        html.Div([html.Strong("Pos/Repo: "), f"${calc['ballast_hire_cost_usd'] + calc['ballast_bog_fuel_cost_usd']:,.0f}"],
                style={'margin-bottom': '0', 'line-height': '1.2'},
                title=f"Ballast Hire: ${calc['ballast_hire_cost_usd']:,.0f} + Ballast Fuel: ${calc['ballast_bog_fuel_cost_usd']:,.0f}"),
        html.Div([html.Strong("Total: "), f"${calc['laden_hire_cost_usd'] + calc['ballast_hire_cost_usd'] + calc['ballast_bog_fuel_cost_usd']:,.0f}"],
                style={'margin-bottom': '1px', 'font-weight': 'bold', 'background-color': '#e3f2fd', 'padding': '2px 4px'},
                title=f"Total Charter $$$: Laden Hire ${calc['laden_hire_cost_usd']:,.0f} + Pos/Repo (Ballast Hire ${calc['ballast_hire_cost_usd']:,.0f} + Ballast Fuel ${calc['ballast_bog_fuel_cost_usd']:,.0f}) = ${calc['laden_hire_cost_usd'] + calc['ballast_hire_cost_usd'] + calc['ballast_bog_fuel_cost_usd']:,.0f}"),
    ])

    # Build Charter Costs section
    charter_costs_content = html.Div([
        html.H5("Charter Costs", style={
            'background-color': '#2E86C1',
            'color': 'white',
            'padding': '6px',
            'margin': '-8px -8px 4px -8px',
            'font-size': '12px'
        }),
        html.Div([html.Strong("Pos/Repo $: "),
                 f"${calc['ballast_bog_fuel_cost_usd']:,.0f}"],
                style={'margin-bottom': '0', 'line-height': '1.2'},
                title=f"Ballast Voy Fuel: {ballast_fuel_cbm:,.0f} m³ | {ballast_fuel_mmbtu:,.0f} mmbtu = ${calc['ballast_bog_fuel_cost_usd']:,.0f}"),
        html.Div([html.Strong("Other $: "), "$0"],
                style={'margin-bottom': '0', 'line-height': '1.2'}),
        html.Div([html.Strong("Total: "), f"${calc['ballast_bog_fuel_cost_usd']:,.0f}"],
                style={'margin-bottom': '4px', 'font-weight': 'bold', 'background-color': '#e3f2fd', 'padding': '2px 4px'},
                title=f"Total Charter Costs: Pos/Repo $ ${calc['ballast_bog_fuel_cost_usd']:,.0f} + Other $ $0 = ${calc['ballast_bog_fuel_cost_usd']:,.0f}"),
    ])

    # Build Summary TCE section (left column)
    # TCE = (Total Charter $$$ - Total Charter Costs) / Voy Days
    # Lump Sum = TCE × Voy Days
    total_charter_revenue = calc['laden_hire_cost_usd'] + calc['ballast_hire_cost_usd'] + calc['ballast_bog_fuel_cost_usd']
    total_charter_costs = calc['ballast_bog_fuel_cost_usd']
    tce = (total_charter_revenue - total_charter_costs) / calc['voy_days']
    lump_sum = tce * calc['voy_days']

    summary_tce_content = html.Div([
        html.H5("Summary TCE", style={
            'background-color': '#2E86C1',
            'color': 'white',
            'padding': '6px',
            'margin': '-8px -8px 4px -8px',
            'font-size': '12px'
        }),
        html.Div([html.Strong("TCE: "), f"${tce:,.0f}/days"],
                style={'margin-bottom': '0', 'line-height': '1.2'},
                title=f"Time Charter Equivalent: (Total Charter $$$ ${total_charter_revenue:,.0f} - Total Charter Costs ${total_charter_costs:,.0f}) / {calc['voy_days']} days = ${tce:,.0f}/day"),
        html.Div([html.Strong("Lump Sum: "), f"${lump_sum:,.0f}"],
                style={'margin-bottom': '4px'},
                title=f"Lump Sum: TCE ${tce:,.0f}/day × {calc['voy_days']} days = ${lump_sum:,.0f}"),
    ])

    # Build Summary section (right column - UFC only)
    summary_content = html.Div([
        html.H5("Summary", style={
            'background-color': '#2E86C1',
            'color': 'white',
            'padding': '6px',
            'margin': '-8px -8px 4px -8px',
            'font-size': '12px'
        }),
        html.Div([html.Strong("Voy Costs: "), f"${calc['voy_costs_usd']:,.0f}"],
                style={'margin-bottom': '0', 'line-height': '1.2'},
                title=f"Voyage Costs: Laden Total ${calc['laden_total_cost_usd']:,.0f} + Ballast Total ${calc['ballast_total_cost_usd']:,.0f} = ${calc['voy_costs_usd']:,.0f}"),
        html.Div([html.Strong("$/day UFC: "), f"{calc['voy_ufc_usd_mmbtu'] / calc['voy_days']:.4f} $/mmbtu"],
                style={'margin-bottom': '0', 'line-height': '1.2'},
                title=f"Daily UFC: Voy UFC ${calc['voy_ufc_usd_mmbtu']:.4f}/mmbtu / {calc['voy_days']} days = ${calc['voy_ufc_usd_mmbtu'] / calc['voy_days']:.4f}/mmbtu per day"),
        html.Div([html.Strong("Voy UFC: "), f"{calc['voy_ufc_usd_mmbtu']:.4f} $/mmbtu"],
                style={
                    'margin-bottom': '0',
                    'line-height': '1.2',
                    'font-weight': 'bold',
                    'padding': '4px',
                    'background-color': '#f0f8ff',
                    'border-radius': '4px'
                },
                title=f"Voyage UFC: Voy Costs ${calc['voy_costs_usd']:,.0f} / DES Volume {calc['des_volume_mmbtu']:,.0f} mmbtu = ${calc['voy_ufc_usd_mmbtu']:.4f}/mmbtu"),
    ])

    # Build route header (darker blue banner spanning both columns)
    route_header = f"Load Port: {config['load_port_name']} → Disch Port: {config['discharge_port_name']} ({config['region']})"

    return (route_header, charter_content, laden_voy_content, ballast_voy_content,
            market_prices_content, charter_summary_content,
            charter_costs_content, summary_tce_content, summary_content)
