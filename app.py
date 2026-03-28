"""
Dash App Instance for UFC Calculator Dashboard

This module creates the core Dash application instance with Bootstrap styling
and configures it for multi-page routing.
"""

from dash import Dash
import dash_bootstrap_components as dbc

# Create Dash app with Bootstrap theme and callback exception suppression
app = Dash(
    __name__,
    external_stylesheets=[dbc.themes.BOOTSTRAP],
    suppress_callback_exceptions=True
)

# Export server for WSGI deployment
server = app.server

# App title
app.title = "UFC Calculator Dashboard"
