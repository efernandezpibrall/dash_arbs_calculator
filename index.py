"""
Main Entry Point for UFC Calculator Dash Application

This module sets up the app layout and runs the development server.
Multi-page application with routing for calculator and port costs pages.
"""

from app import app
from dash import html, dcc, callback, Output, Input
import pages.calculator
import pages.port_costs

# Set app layout with multi-page routing
app.layout = html.Div([
    dcc.Location(id='url', refresh=False),
    html.Div(id='page-content')
])

@callback(
    Output('page-content', 'children'),
    Input('url', 'pathname')
)
def display_page(pathname):
    """Route between pages based on URL pathname"""
    if pathname == '/port-costs':
        return pages.port_costs.layout
    else:
        # Default to calculator page
        return pages.calculator.layout

if __name__ == '__main__':
    print("=" * 70) 
    print("UFC Calculator Dashboard")
    print("=" * 70)
    print("\nStarting Dash application...")
    print("Access the dashboard at: http://localhost:8050")
    print("\nPress Ctrl+C to stop the server.")
    print("=" * 70)

    app.run(debug=True, host='0.0.0.0', port=8050)
