"""FastAPI web application for E-Ink Photo Frame."""

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from web.routes import router

logger = logging.getLogger(__name__)

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

# Middleware to log ALL requests (for captive portal debugging)
@app.middleware("http")
async def log_all_requests(request: Request, call_next):
    """Log all incoming HTTP requests with full details."""
    host = request.headers.get("host", "unknown")
    logger.info(f"HTTP Request: {request.method} {request.url.path} (Host: {host}, Client: {request.client.host if request.client else 'unknown'})")
    response = await call_next(request)

    # 첫 접속 감지: no_connection 타이머 → idle 타이머 전환
    path = request.url.path
    if path == "/" or path.startswith("/api/"):
        try:
            from state_machine import get_state_machine
            sm = get_state_machine()
            if sm:
                sm.notify_web_connection()
        except Exception:
            pass

    return response


# Include API routes
app.include_router(router)


def get_templates() -> Jinja2Templates:
    """Get Jinja2 templates instance."""
    return templates
