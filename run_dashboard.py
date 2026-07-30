"""
RustDesk API Server — Launcher
Starts the FastAPI server on port 21114 (standard RustDesk API server port).
"""

import os
import sys
import webbrowser
import threading
import time
import subprocess

# Server config
HOST = "0.0.0.0"
PORT = 21114
DASHBOARD_URL = f"http://localhost:{PORT}/admin"

def free_port(port: int):
    """Kill any existing process listening on port."""
    current_pid = os.getpid()
    if os.name == "nt":
        try:
            cmd = f'netstat -ano | findstr :{port}'
            out = subprocess.check_output(cmd, shell=True, text=True, errors="ignore")
            pids = set()
            for line in out.strip().splitlines():
                parts = line.split()
                if len(parts) >= 5 and "LISTENING" in parts:
                    try:
                        pid = int(parts[-1])
                        if pid > 0 and pid != current_pid:
                            pids.add(pid)
                    except ValueError:
                        pass
            for pid in pids:
                print(f"  -> Killing existing process listening on port {port} (PID {pid})...")
                subprocess.run(f"taskkill /F /PID {pid}", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                time.sleep(0.5)
        except Exception:
            pass
    else:
        try:
            cmd = f"lsof -t -i:{port}"
            pids_out = subprocess.check_output(cmd, shell=True, text=True).strip()
            for pid_str in pids_out.splitlines():
                pid = int(pid_str.strip())
                if pid != current_pid:
                    subprocess.run(["kill", "-9", str(pid)])
        except Exception:
            pass

def open_browser():
    """Open the dashboard in the browser after a short delay."""
    time.sleep(2)
    print(f"\n  -> Opening dashboard: {DASHBOARD_URL}")
    print(f"  -> Default login: admin / admin123")
    print(f"  -> Set API server in RustDesk client to: http://<your-ip>:{PORT}\n")
    webbrowser.open(DASHBOARD_URL)

def main():
    # Kill anything currently using port 21114
    free_port(PORT)

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

