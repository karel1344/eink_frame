"""FastAPI web application for E-Ink Photo Frame."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .routes import router

# Paths
BASE_DIR = Path(__file__).parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

# Create FastAPI app
app = FastAPI(
    title="E-Ink Photo Frame",
    description="Web UI for E-Ink Photo Frame configuration",
    version="0.1.0",
)

# Mount static files
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Templates
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# Include API routes
app.include_router(router)


def get_templates() -> Jinja2Templates:
    """Get Jinja2 templates instance."""
    return templates
