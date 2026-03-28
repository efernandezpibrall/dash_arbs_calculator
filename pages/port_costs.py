"""
Port Costs Management Page

This module provides a data entry/editing interface for port operations costs.
Users can view and edit LNG port costs by vessel type, with full audit trail.

Features:
- View latest port costs (one version per port/terminal)
- Edit costs directly in AG Grid
- Append-only versioning with author tracking
- Excel export capability
"""

from dash import html, dcc, callback, Output, Input, State
import dash_ag_grid as dag
import dash_bootstrap_components as dbc
import pandas as pd
import datetime as dt

import configparser
import os
from sqlalchemy import create_engine, text

# ========================================
# Database Connection
# ========================================
try:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_dir = os.path.abspath(os.path.join(script_dir, '../..'))
    CONFIG_FILE_PATH = os.path.join(config_dir, 'config.ini')
except:
    CONFIG_FILE_PATH = '../config.ini'

config_reader = configparser.ConfigParser(interpolation=None)
config_reader.read(CONFIG_FILE_PATH)

DB_CONNECTION_STRING = config_reader.get('DATABASE', 'CONNECTION_STRING', fallback=None)
DB_SCHEMA = config_reader.get('DATABASE', 'SCHEMA', fallback='at_lng')

if not DB_CONNECTION_STRING:
    raise ValueError(f"Missing DATABASE CONNECTION_STRING in {CONFIG_FILE_PATH}")

engine = create_engine(DB_CONNECTION_STRING, pool_pre_ping=True)

# ========================================
# Style Constants
# ========================================
STYLES = {
    'page_header': {
        'color': '#1f2937',
        'font-weight': '600',
        'font-size': '32px',
        'font-family': 'Inter, -apple-system, BlinkMacSystemFont, sans-serif'
    },
    'icon_primary': {
        'color': '#2E86C1'
    },
    'section_header': {
        'color': '#1f2937',
        'font-weight': '500',
        'font-size': '22px',
        'font-family': 'Inter, -apple-system, BlinkMacSystemFont, sans-serif'
    },
    'card_header': {
        'background': '#f8fafc',
        'border': 'none',
        'font-weight': '500',
        'font-size': '16px',
        'padding': '14px 18px',
        'border-radius': '6px'
    },
    'section_container': {
        'background': '#f8fafc',
        'border-bottom': '1px solid #cbd5e1',
        'padding': '14px 18px',
        'border-radius': '6px'
    },
    'table_container': {
        'border': '1px solid #cbd5e1',
        'border-radius': '6px',
        'padding': '16px'
    },
}

# ========================================
# Helper Functions
# ========================================

def clean_numeric_value(value):
    """Convert empty strings and invalid values to None for numeric DB columns"""
    if value is None or value == '' or value == 'None':
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def get_port_costs_latest():
    """Fetch latest port costs from view"""
    query = """
        SELECT
            region, country, port, terminal, lng_terminal_facility_name,
            vessel_type_145k_steam_usd, vessel_type_160k_tfde_usd,
            vessel_type_174k_megi_usd, vessel_type_qflex_usd, vessel_type_qmax_usd,
            loading_discharge, remarks,
            upload_timestamp_utc, uploaded_by
        FROM at_lng.shipping_inputs_port_costs_latest
        ORDER BY region, country, port, terminal NULLS LAST
    """

    with engine.connect() as conn:
        df = pd.read_sql(query, conn)

    # Format timestamp
    if 'upload_timestamp_utc' in df.columns:
        df['upload_timestamp_utc'] = pd.to_datetime(df['upload_timestamp_utc']).dt.strftime('%Y-%m-%d %H:%M UTC')

    # Fill NaN with empty string for display
    df = df.fillna('')

    return df


def save_port_costs_changes(changed_rows, uploaded_by):
    """Save port cost changes as new versions (append-only)"""
    timestamp_utc = dt.datetime.now(dt.timezone.utc)
    inserted_count = 0

    with engine.begin() as conn:
        for row in changed_rows:
            insert_sql = f"""
            INSERT INTO {DB_SCHEMA}.shipping_inputs_port_costs
                (region, country, port, terminal, lng_terminal_facility_name,
                 vessel_type_145k_steam_usd, vessel_type_160k_tfde_usd,
                 vessel_type_174k_megi_usd, vessel_type_qflex_usd, vessel_type_qmax_usd,
                 loading_discharge, remarks, upload_timestamp_utc, uploaded_by)
            VALUES
                (:region, :country, :port, :terminal, :lng_terminal_facility_name,
                 :v145k, :v160k, :v174k, :vqflex, :vqmax,
                 :loading_discharge, :remarks, :timestamp, :uploaded_by)
            """

            params = {
                'region': row.get('region'),
                'country': row.get('country'),
                'port': row.get('port'),
                'terminal': row.get('terminal') or None,
                'lng_terminal_facility_name': row.get('lng_terminal_facility_name') or None,
                'v145k': clean_numeric_value(row.get('vessel_type_145k_steam_usd')),
                'v160k': clean_numeric_value(row.get('vessel_type_160k_tfde_usd')),
                'v174k': clean_numeric_value(row.get('vessel_type_174k_megi_usd')),
                'vqflex': clean_numeric_value(row.get('vessel_type_qflex_usd')),
                'vqmax': clean_numeric_value(row.get('vessel_type_qmax_usd')),
                'loading_discharge': row.get('loading_discharge') or None,
                'remarks': row.get('remarks') or None,
                'timestamp': timestamp_utc,
                'uploaded_by': uploaded_by
            }

            conn.execute(text(insert_sql), params)
            inserted_count += 1

    return True, f"Successfully inserted {inserted_count} new version(s)"


# ========================================
# Navigation Bar
# ========================================
navbar = dbc.NavbarSimple(
    children=[
        dbc.NavItem(dbc.NavLink("UFC Calculator", href="/")),
        dbc.NavItem(dbc.NavLink("Port Costs", href="/port-costs", active=True)),
    ],
    brand="UFC Calculator Dashboard",
    brand_href="/",
    color="primary",
    dark=True,
    className="mb-3",
    fluid=True
)

# ========================================
# Page Layout
# ========================================

layout = html.Div([
    navbar,

    dbc.Container([
        # Page Header
        html.Div([
            html.Div([
                html.I(className="bi bi-cash-coin me-3", style=STYLES['icon_primary']),
                html.Span("Port Costs Management", style=STYLES['page_header']),
            ], className="d-flex align-items-center"),
        ], className="mb-3"),

        # Actions Card
        dbc.Card([
            dbc.CardBody([
                dbc.Row([
                    dbc.Col([
                        dbc.Button(
                            [html.I(className="bi bi-arrow-clockwise me-2"), "Refresh Data"],
                            id="port-costs-refresh-btn",
                            color="primary",
                            size="sm",
                            className="me-2"
                        ),
                        dbc.Button(
                            [html.I(className="bi bi-save me-2"), "Save Changes"],
                            id="port-costs-save-btn",
                            color="success",
                            size="sm",
                            className="me-2"
                        ),
                        dbc.Button(
                            [html.I(className="bi bi-file-earmark-excel me-2"), "Export to Excel"],
                            id="port-costs-export-btn",
                            color="info",
                            size="sm",
                        ),
                    ], width=8),
                    dbc.Col([
                        html.Div([
                            html.Label(
                                "Author Name:",
                                style={'fontSize': '16px', 'fontWeight': '400', 'color': '#4b5563', 'marginRight': '10px'}
                            ),
                            dcc.Input(
                                id="port-costs-author-input",
                                type="text",
                                placeholder="Your initials",
                                style={'width': '200px', 'fontSize': '16px'},
                                maxLength=50,
                                required=True
                            ),
                        ], className="d-flex align-items-center justify-content-end"),
                    ], width=4),
                ], align="center"),

                # Status Alert
                html.Div([
                    dbc.Alert(
                        id="port-costs-status-alert",
                        is_open=False,
                        duration=4000,
                        className="mt-3 mb-0"
                    ),
                ]),

                # Last Update Display
                html.Div([
                    html.Small(
                        id="port-costs-last-update-text",
                        style={'color': '#6b7280', 'fontSize': '14px'}
                    ),
                ], className="mt-2"),
            ], className="py-3"),
        ], className="mb-3"),

        # Data Grid Card
        dbc.Card([
            dbc.CardBody([
                html.Div([
                    dag.AgGrid(
                        id='port-costs-grid',
                        columnDefs=[
                            # Location columns (non-editable, pinned)
                            {"field": "region", "headerName": "Region", "width": 120, "editable": False, "pinned": "left"},
                            {"field": "country", "headerName": "Country", "width": 150, "editable": False, "pinned": "left"},
                            {"field": "port", "headerName": "Port", "width": 180, "editable": False, "pinned": "left"},
                            {"field": "terminal", "headerName": "Terminal", "width": 180, "editable": False},
                            {"field": "lng_terminal_facility_name", "headerName": "Facility Name", "width": 250, "editable": False},
                            {"field": "loading_discharge", "headerName": "Loading/Discharge", "width": 160, "editable": True},

                            # Vessel type costs (editable, numeric)
                            {
                                "field": "vessel_type_145k_steam_usd",
                                "headerName": "145k Steam (USD)",
                                "width": 170,
                                "editable": True,
                                "type": "numericColumn",
                                "valueFormatter": {"function": "params.value != null && params.value !== '' ? d3.format(',.2f')(params.value) : ''"}
                            },
                            {
                                "field": "vessel_type_160k_tfde_usd",
                                "headerName": "160k TFDE (USD)",
                                "width": 170,
                                "editable": True,
                                "type": "numericColumn",
                                "valueFormatter": {"function": "params.value != null && params.value !== '' ? d3.format(',.2f')(params.value) : ''"}
                            },
                            {
                                "field": "vessel_type_174k_megi_usd",
                                "headerName": "174k MEGI (USD)",
                                "width": 170,
                                "editable": True,
                                "type": "numericColumn",
                                "valueFormatter": {"function": "params.value != null && params.value !== '' ? d3.format(',.2f')(params.value) : ''"}
                            },
                            {
                                "field": "vessel_type_qflex_usd",
                                "headerName": "Q-Flex (USD)",
                                "width": 150,
                                "editable": True,
                                "type": "numericColumn",
                                "valueFormatter": {"function": "params.value != null && params.value !== '' ? d3.format(',.2f')(params.value) : ''"}
                            },
                            {
                                "field": "vessel_type_qmax_usd",
                                "headerName": "Q-Max (USD)",
                                "width": 150,
                                "editable": True,
                                "type": "numericColumn",
                                "valueFormatter": {"function": "params.value != null && params.value !== '' ? d3.format(',.2f')(params.value) : ''"}
                            },

                            # Metadata columns (non-editable)
                            {"field": "remarks", "headerName": "Remarks", "width": 200, "editable": True},
                            {"field": "upload_timestamp_utc", "headerName": "Last Updated", "width": 180, "editable": False},
                            {"field": "uploaded_by", "headerName": "Updated By", "width": 130, "editable": False},
                        ],
                        defaultColDef={
                            "sortable": True,
                            "resizable": True,
                        },
                        dashGridOptions={
                            "enterNavigatesVertically": True,
                            "enterNavigatesVerticallyAfterEdit": True,
                            "singleClickEdit": False,  # Double-click to edit
                            "undoRedoCellEditing": True,
                            "undoRedoCellEditingLimit": 20,
                            "stopEditingWhenCellsLoseFocus": True,
                            "animateRows": True,
                            "enableRangeSelection": True,
                            "rowHeight": 42,
                            "domLayout": "normal",  # Standard scrolling
                        },
                        getRowStyle={
                            "styleConditions": [
                                {
                                    "condition": "params.node.rowIndex % 2 === 1",
                                    "style": {"backgroundColor": "#f8f9fa", "fontSize": "16px"}
                                },
                            ]
                        },
                        className="ag-theme-alpine",
                        style={"width": "100%", "height": "650px", "fontSize": "16px"}
                    ),
                ]),
            ], className="p-3"),
        ], className="mb-4"),

        # Data Stores
        dcc.Store(id='port-costs-original-data', storage_type='memory'),
        dcc.Store(id='port-costs-last-update', storage_type='memory'),
        dcc.Download(id='port-costs-export-download'),

    ], fluid=True),
])


# ========================================
# Callbacks
# ========================================

@callback(
    Output('port-costs-grid', 'rowData'),
    Output('port-costs-original-data', 'data'),
    Output('port-costs-last-update', 'data'),
    Input('port-costs-refresh-btn', 'n_clicks'),
)
def load_port_costs_data(n_clicks):
    """Load port costs data from database"""
    df = get_port_costs_latest()
    original_data = df.to_dict('records')

    # Get most recent timestamp
    timestamps = df['upload_timestamp_utc'].dropna()
    last_update = timestamps.max() if len(timestamps) > 0 else None

    return df.to_dict('records'), original_data, last_update


@callback(
    Output('port-costs-status-alert', 'children'),
    Output('port-costs-status-alert', 'is_open'),
    Output('port-costs-status-alert', 'color'),
    Input('port-costs-save-btn', 'n_clicks'),
    State('port-costs-grid', 'rowData'),
    State('port-costs-original-data', 'data'),
    State('port-costs-author-input', 'value'),
    prevent_initial_call=True
)
def save_changes(n_clicks, table_data, original_data, author_name):
    """Save port cost changes to database"""
    # Validate author
    if not author_name or author_name.strip() == "":
        return [
            html.I(className="bi bi-exclamation-triangle me-2"),
            "Please enter your name/initials before saving."
        ], True, "danger"

    # Detect changed rows
    original_lookup = {
        f"{row['region']}_{row['country']}_{row['port']}_{row.get('terminal', '')}": row
        for row in original_data
    }

    changed_rows = []
    for current_row in table_data:
        key = f"{current_row['region']}_{current_row['country']}_{current_row['port']}_{current_row.get('terminal', '')}"

        if key in original_lookup:
            original_row = original_lookup[key]
            # Compare all editable fields
            if (current_row.get('vessel_type_145k_steam_usd') != original_row.get('vessel_type_145k_steam_usd') or
                current_row.get('vessel_type_160k_tfde_usd') != original_row.get('vessel_type_160k_tfde_usd') or
                current_row.get('vessel_type_174k_megi_usd') != original_row.get('vessel_type_174k_megi_usd') or
                current_row.get('vessel_type_qflex_usd') != original_row.get('vessel_type_qflex_usd') or
                current_row.get('vessel_type_qmax_usd') != original_row.get('vessel_type_qmax_usd') or
                current_row.get('loading_discharge') != original_row.get('loading_discharge') or
                current_row.get('remarks') != original_row.get('remarks')):
                changed_rows.append(current_row)

    if len(changed_rows) == 0:
        return [
            html.I(className="bi bi-info-circle me-2"),
            "No changes detected."
        ], True, "info"

    # Save changes
    try:
        success, message = save_port_costs_changes(changed_rows, author_name.strip())
        if success:
            return [
                html.I(className="bi bi-check-circle me-2"),
                message
            ], True, "success"
        else:
            return [
                html.I(className="bi bi-exclamation-triangle me-2"),
                message
            ], True, "danger"
    except Exception as e:
        return [
            html.I(className="bi bi-exclamation-triangle me-2"),
            f"Error saving changes: {str(e)}"
        ], True, "danger"


@callback(
    Output('port-costs-export-download', 'data'),
    Input('port-costs-export-btn', 'n_clicks'),
    State('port-costs-grid', 'rowData'),
    prevent_initial_call=True
)
def export_data(n_clicks, table_data):
    """Export port costs data to Excel"""
    df = pd.DataFrame(table_data)
    timestamp = dt.datetime.now().strftime('%Y%m%d_%H%M%S')
    return dcc.send_data_frame(df.to_excel, f"port_costs_{timestamp}.xlsx", index=False)


@callback(
    Output('port-costs-author-input', 'style'),
    Input('port-costs-author-input', 'value')
)
def update_author_style(value):
    """Update author input border color based on validation"""
    base_style = {'width': '200px', 'fontSize': '16px'}
    if value and len(value.strip()) >= 2:
        base_style['border'] = '2px solid #28a745'  # Green
    else:
        base_style['border'] = '2px solid #dc3545'  # Red
    return base_style


@callback(
    Output('port-costs-last-update-text', 'children'),
    Input('port-costs-last-update', 'data')
)
def update_last_update_display(last_update):
    """Display last update timestamp"""
    if last_update:
        return f"Last updated: {last_update}"
    return "Last updated: N/A"
