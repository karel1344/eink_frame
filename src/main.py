"""E-Ink Photo Frame main entry point."""

import uvicorn


def main():
    """Run the web server for development."""
    from src.web.app import app

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,  # Use 8000 for development, 80 on Pi
        reload=True,
    )


if __name__ == "__main__":
    main()
