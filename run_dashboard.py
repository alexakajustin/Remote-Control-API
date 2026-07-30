"""
RustDesk API Server — Launcher
Starts the FastAPI server on port 21114 (standard RustDesk API server port).
"""

import os
import sys
import webbrowser
import threading
import time

# Server config
HOST = "0.0.0.0"
PORT = 21114
DASHBOARD_URL = f"http://localhost:{PORT}/admin"

def open_browser():
    """Open the dashboard in the browser after a short delay."""
    time.sleep(2)
    print(f"\n  -> Opening dashboard: {DASHBOARD_URL}")
    print(f"  -> Default login: admin / admin123")
    print(f"  -> Set API server in RustDesk client to: http://<your-ip>:{PORT}\n")
    webbrowser.open(DASHBOARD_URL)

def main():
    # Set working directory to backend
    backend_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Dashboard", "backend")
    sys.path.insert(0, backend_dir)

    print("=" * 60)
    print("  RustDesk API Server")
    print("=" * 60)
    print(f"  Port:      {PORT}")
    print(f"  Dashboard: {DASHBOARD_URL}")
    print(f"  API:       http://0.0.0.0:{PORT}/api/")
    print("=" * 60)

    # Open browser in background
    threading.Thread(target=open_browser, daemon=True).start()

    # Start uvicorn
    import uvicorn
    os.chdir(backend_dir)
    uvicorn.run(
        "main:app",
        host=HOST,
        port=PORT,
        log_level="info",
        reload=False,
    )

if __name__ == "__main__":
    main()
