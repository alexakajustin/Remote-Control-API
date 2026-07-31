"""
RustDesk API Server — Main FastAPI Application
Implements the RustDesk client protocol endpoints + admin dashboard API.
Runs on port 21114 (standard RustDesk API server port).
"""

import os
import sys
import time
import json
import asyncio
import logging
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException, WebSocket, WebSocketDisconnect, Query
from fastapi.responses import JSONResponse, HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

# Add backend to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import database as db
import auth
from models import (
    LoginRequest, LoginResponse, HeartbeatRequest, SysInfoRequest,
    CurrentUserRequest, AddressBookRequest, AuditRequest,
    CreateUserRequest, UpdateUserRequest
)

# ─── Config ───
SERVER_START_TIME = time.time()
HEARTBEAT_TIMEOUT = 90  # seconds before marking device offline
LOG_EVENTS = []  # In-memory event log for real-time dashboard
MAX_LOG_EVENTS = 500

# WebSocket connections for live dashboard
ws_clients: set = set()

logger = logging.getLogger("rustdesk-api")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def add_log_event(event_type: str, message: str, data: dict = None):
    """Add an event to the in-memory log and broadcast to WebSocket clients."""
    event = {
        "timestamp": time.time(),
        "type": event_type,
        "message": message,
        "data": data or {}
    }
    LOG_EVENTS.insert(0, event)
    if len(LOG_EVENTS) > MAX_LOG_EVENTS:
        LOG_EVENTS.pop()
    # Schedule broadcast
    asyncio.create_task(broadcast_ws({"type": "event", "event": event}))


async def broadcast_ws(data: dict):
    """Broadcast a message to all connected WebSocket dashboard clients."""
    dead = set()
    msg = json.dumps(data)
    for ws in ws_clients:
        try:
            await ws.send_text(msg)
        except Exception:
            dead.add(ws)
    ws_clients.difference_update(dead)


GLOBAL_HEALTH = {
    "isp_ping": "unknown",
    "rustdesk_services": "unknown",
    "last_check": 0
}

async def ping_ip(ip: str) -> bool:
    try:
        cmd = ["ping", "-n", "1", "-w", "1000", ip] if os.name == 'nt' else ["ping", "-c", "1", "-W", "1", ip]
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        await proc.wait()
        return proc.returncode == 0
    except Exception:
        return False

async def check_tcp_port(ip: str, port: int, timeout: int = 2) -> bool:
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(ip, port), timeout=timeout)
        writer.close()
        await writer.wait_closed()
        return True
    except Exception:
        return False

async def health_checker():
    """Background task to check system health and monitored endpoints."""
    while True:
        try:
            # Check ISP
            isp_ok = await ping_ip("1.1.1.1") or await ping_ip("8.8.8.8")
            GLOBAL_HEALTH["isp_ping"] = "online" if isp_ok else "offline"
            
            # Check RustDesk local services (hbbs 21115, hbbr 21116)
            # Just check one for simplicity, or both
            hbbs_ok = await check_tcp_port("127.0.0.1", 21115)
            GLOBAL_HEALTH["rustdesk_services"] = "online" if hbbs_ok else "offline"
            GLOBAL_HEALTH["last_check"] = time.time()
            
            # Check monitored endpoints
            endpoints = db.get_all_devices()
            for ep in endpoints:
                ip = ep["ip"]
                if not ip:
                    continue
                
                status_ping = ep["status_ping"]
                status_rdp = ep["status_rdp"]
                
                if ep.get("check_ping", 1):
                    status_ping = "online" if await ping_ip(ip) else "offline"
                else:
                    status_ping = "unknown"
                
                if ep["check_rdp"] and ep["rdp_port"]:
                    status_rdp = "online" if await check_tcp_port(ip, ep["rdp_port"]) else "offline"
                
                db.update_device_status_ping_rdp(ep["id"], status_ping, status_rdp)
                
        except Exception as e:
            logger.error(f"Health checker error: {e}")
        
        await asyncio.sleep(10)


async def heartbeat_checker():
    """Background task to mark stale devices as offline."""
    while True:
        await asyncio.sleep(30)
        try:
            db.mark_stale_devices(HEARTBEAT_TIMEOUT)
        except Exception as e:
            logger.error(f"Heartbeat checker error: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle."""
    # Initialize database
    db.init_db()
    logger.info("Database initialized")

    # Create default admin if no users exist
    users = db.get_all_users()
    if not users:
        pw_hash = auth.hash_password("admin123")
        db.create_user("admin", pw_hash, name="Administrator", is_admin=1)
        logger.info("Created default admin user: admin / admin123")

    # Start background heartbeat checker
    task1 = asyncio.create_task(heartbeat_checker())
    task2 = asyncio.create_task(health_checker())
    add_log_event("server", "RustDesk API Server started")

    yield

    task1.cancel()
    task2.cancel()
    logger.info("Server shutting down")


# ─── App ───
app = FastAPI(title="RustDesk API Server", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve frontend static files
FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")


# ─── Helper: Auth check ───

def get_current_user(request: Request):
    """Extract and validate the user from the Authorization header."""
    auth_header = request.headers.get("Authorization", "")
    token = auth.extract_token_from_header(auth_header)
    if not token:
        return None
    payload = auth.decode_jwt(token)
    if not payload:
        return None
    user = db.get_user_by_id(payload.get("user_id", 0))
    return user


def require_auth(request: Request):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return user


def require_admin(request: Request):
    user = require_auth(request)
    if not user["is_admin"]:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


# ═══════════════════════════════════════════════════════════════════
# RustDesk Client API Endpoints (what the client calls)
# ═══════════════════════════════════════════════════════════════════

@app.post("/api/login")
async def api_login(request: Request):
    """RustDesk client login."""
    try:
        body = await request.json()
    except Exception:
        body = {}

    username = body.get("username", "")
    password = body.get("password", "")
    device_id = body.get("id", "")
    uuid = body.get("uuid", "")

    if not username or not password:
        return JSONResponse(content={"error": "Username and password required"}, status_code=401)

    user = db.get_user_by_username(username)
    if not user or not auth.verify_password(password, user["password_hash"]):
        add_log_event("auth", f"Failed login attempt: {username} from device {device_id}")
        return JSONResponse(content={"error": "Invalid credentials"}, status_code=401)

    # Create JWT token
    token = auth.create_jwt({
        "user_id": user["id"],
        "username": user["username"],
        "is_admin": bool(user["is_admin"]),
    })

    # Create session
    db.create_session(user["id"], device_id, token)

    # If device info provided, register device
    if device_id:
        device_info = body.get("deviceInfo", {})
        db.upsert_device(
            device_id=device_id,
            uuid=uuid,
            user_id=user["id"],
            hostname=device_info.get("hostname", ""),
            os_name=device_info.get("os", ""),
            ip=request.client.host if request.client else "",
        )

    add_log_event("auth", f"User '{username}' logged in from device {device_id}", {"device_id": device_id})
    logger.info(f"Login: user={username} device={device_id}")

    return JSONResponse(content={
        "access_token": token,
        "type": "access_token",
        "tfa_type": "",
        "secret": "",
        "user": {
            "name": user["name"] or user["username"],
            "email": user["email"],
            "note": "",
            "status": user["status"],
            "is_admin": bool(user["is_admin"]),
            "grp": "",
        }
    })


@app.post("/api/logout")
async def api_logout(request: Request):
    """RustDesk client logout."""
    auth_header = request.headers.get("Authorization", "")
    token = auth.extract_token_from_header(auth_header)
    if token:
        db.invalidate_session(token)
        add_log_event("auth", "User logged out")
    return JSONResponse(content={"error": ""})


@app.post("/api/currentUser")
async def api_current_user(request: Request):
    """Get current logged-in user info."""
    user = get_current_user(request)
    if not user:
        return JSONResponse(content={"error": "Not logged in"}, status_code=401)
    return JSONResponse(content={
        "error": "",
        "data": {
            "name": user["name"] or user["username"],
            "email": user["email"],
            "note": "",
            "status": user["status"],
            "is_admin": bool(user["is_admin"]),
            "grp": "",
        }
    })


@app.post("/api/heartbeat")
async def api_heartbeat(request: Request):
    """RustDesk client heartbeat — reports device is alive with system info."""
    try:
        body = await request.json()
    except Exception:
        body = {}

    device_id = body.get("id", "")
    uuid = body.get("uuid", "")

    if not device_id:
        return JSONResponse(content={"error": ""})

    client_ip = request.client.host if request.client else ""

    # Determine user from auth token if available
    user = get_current_user(request)
    user_id = user["id"] if user else None

    # Update device
    db.upsert_device(
        device_id=device_id,
        uuid=uuid,
        user_id=user_id,
        hostname=body.get("hostname", ""),
        os_name=body.get("os", ""),
        version=body.get("version", ""),
        cpu=body.get("cpu", ""),
        memory=body.get("memory", ""),
        ip=client_ip,
        info=body,
    )

    # Record heartbeat
    db.record_heartbeat(device_id, client_ip, body)

    return JSONResponse(content={"error": "", "modified_at": ""})


@app.post("/api/sysinfo")
async def api_sysinfo(request: Request):
    """RustDesk client system info update."""
    try:
        body = await request.json()
    except Exception:
        body = {}

    device_id = body.get("id", "")
    logger.info(f"Sysinfo from {device_id}: {json.dumps(body)}")
    if device_id:
        user = get_current_user(request)
        user_id = user["id"] if user else None
        client_ip = request.client.host if request.client else ""

        db.upsert_device(
            device_id=device_id,
            uuid=body.get("uuid", ""),
            user_id=user_id,
            hostname=body.get("hostname", ""),
            os_name=body.get("os", ""),
            version=body.get("version", ""),
            cpu=body.get("cpu", ""),
            memory=body.get("memory", ""),
            ip=client_ip,
            info=body,
        )

    return JSONResponse(content={"error": ""})


@app.post("/api/ab")
async def api_address_book(request: Request):
    """RustDesk client address book sync."""
    user = get_current_user(request)
    if not user:
        return JSONResponse(content={"error": "Not logged in"}, status_code=401)

    try:
        body = await request.json()
    except Exception:
        body = {}

    data = body.get("data", None)

    if data is not None:
        # Client is saving address book
        try:
            ab_data = json.loads(data) if isinstance(data, str) else data
        except (json.JSONDecodeError, TypeError):
            ab_data = {}
        db.set_address_book(user["id"], ab_data)
        add_log_event("addressbook", f"User '{user['username']}' updated address book")
        return JSONResponse(content={"error": ""})
    else:
        # Client is fetching address book
        ab_data = db.get_address_book(user["id"])
        return JSONResponse(content={
            "error": "",
            "updated_at": "",
            "data": json.dumps(ab_data) if ab_data else "",
        })


@app.post("/api/ab/personal")
async def api_personal_address_book(request: Request):
    """RustDesk client personal address book."""
    return await api_address_book(request)


@app.get("/api/ab")
async def api_address_book_get(request: Request):
    """GET version of address book fetch."""
    user = get_current_user(request)
    if not user:
        return JSONResponse(content={"error": "Not logged in"}, status_code=401)
    ab_data = db.get_address_book(user["id"])
    return JSONResponse(content={
        "error": "",
        "updated_at": "",
        "data": json.dumps(ab_data) if ab_data else "",
    })


@app.post("/api/audit")
async def api_audit(request: Request):
    """RustDesk client audit event."""
    try:
        body = await request.json()
    except Exception:
        body = {}

    action = body.get("action", "unknown")
    device_id = body.get("id", "") or body.get("Id", "")
    conn_id = str(body.get("conn_id", ""))
    session_id = body.get("session_id", "")
    peer_id = body.get("peer_id", "")
    note = body.get("note", "")
    from_id = body.get("from_id", "") or device_id
    from_ip = body.get("from_ip", "") or body.get("ip", "")
    to_id = body.get("to_id", "") or peer_id
    to_ip = body.get("to_ip", "")

    user = get_current_user(request)
    user_id = user["id"] if user else 0
    client_ip = request.client.host if request.client else ""

    db.add_audit_log(
        action=action,
        source_id=from_id,
        source_ip=from_ip or client_ip,
        target_id=to_id,
        target_ip=to_ip,
        user_id=user_id,
        conn_id=conn_id,
        session_id=session_id,
        note=note,
        info=body,
    )

    add_log_event("audit", f"Audit: {action} -- {from_id} -> {to_id}", {
        "action": action, "from": from_id, "to": to_id
    })

    return JSONResponse(content={"error": ""})


@app.post("/api/audit/conn")
async def api_audit_conn(request: Request):
    """RustDesk client connection audit — this is where 'who connected to who' data comes from."""
    try:
        body = await request.json()
    except Exception:
        body = {}

    logger.info(f"Audit conn payload: {json.dumps(body)}")

    action = body.get("action", "")

    # Parse 'peer' properly (can be a list like ['495722693', 'Alex'])
    peer_raw = body.get("peer_id", "") or body.get("peer", "")
    peer_id = peer_raw[0] if isinstance(peer_raw, list) and len(peer_raw) > 0 else (peer_raw if isinstance(peer_raw, str) else str(peer_raw))
    
    device_id = body.get("id", "") or body.get("Id", "") or body.get("peer_id", "")
    conn_id = str(body.get("conn_id", "") or body.get("connId", ""))
    session_id = body.get("session_id", "") or body.get("sessionId", "")
    from_id = body.get("from", "") or body.get("from_id", "") or device_id
    from_ip = body.get("from_ip", "") or body.get("ip", "")
    to_id = body.get("to", "") or body.get("to_id", "") or peer_id

    # For new_conn and close_conn, the target isn't sent. Look it up from DB using conn_id.
    if not to_id and conn_id:
        with db.get_db() as conn:
            row = conn.execute("SELECT target_id FROM audit_logs WHERE conn_id = ? AND target_id != '' ORDER BY id DESC LIMIT 1", (conn_id,)).fetchone()
            if row:
                to_id = row[0]

    to_ip = body.get("to_ip", "")
    note = body.get("note", "") or body.get("type", "")

    # Map RustDesk action names to our standard names
    action_map = {
        "new": "new_conn",
        "close": "close_conn",
        "open": "new_conn",
        "disconnect": "close_conn",
    }
    mapped_action = action_map.get(action, action or "connect")

    client_ip = request.client.host if request.client else ""

    db.add_audit_log(
        action=mapped_action,
        source_id=from_id,
        source_ip=from_ip or client_ip,
        target_id=to_id,
        target_ip=to_ip,
        conn_id=conn_id,
        session_id=session_id,
        note=note,
        info=body,
    )

    add_log_event("audit", f"Connection: {mapped_action} -- {from_id} -> {to_id}", {
        "action": mapped_action, "from": from_id, "to": to_id
    })

    return JSONResponse(content={"error": ""})


@app.get("/api/users")
async def api_users(request: Request):
    """Client user list."""
    user = get_current_user(request)
    if not user:
        return JSONResponse(content={"error": "Not logged in"}, status_code=401)
    return JSONResponse(content={"error": "", "data": []})


@app.post("/api/users")
async def api_users_post(request: Request):
    return JSONResponse(content={"error": "", "data": []})


# Catch-all for unknown /api/ endpoints — log body for debugging
@app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def api_catch_all(request: Request, path: str):
    """Catch-all for unimplemented API endpoints — prevents client errors."""
    try:
        body = await request.json()
        logger.info(f"Unhandled API call: {request.method} /api/{path} body={json.dumps(body)}")
    except Exception:
        pass
    return JSONResponse(content={"error": "", "data": {}})


# ═══════════════════════════════════════════════════════════════════
# Admin Dashboard API (what the web dashboard calls)
# ═══════════════════════════════════════════════════════════════════

@app.post("/admin/api/login")
async def admin_login(request: Request):
    """Admin dashboard login."""
    try:
        body = await request.json()
    except Exception:
        body = {}

    username = body.get("username", "")
    password = body.get("password", "")

    user = db.get_user_by_username(username)
    if not user or not auth.verify_password(password, user["password_hash"]):
        return JSONResponse(content={"error": "Invalid credentials"}, status_code=401)

    if not user["is_admin"]:
        return JSONResponse(content={"error": "Admin access required"}, status_code=403)

    token = auth.create_jwt({
        "user_id": user["id"],
        "username": user["username"],
        "is_admin": True,
    })
    db.create_session(user["id"], "admin-dashboard", token)

    return JSONResponse(content={
        "token": token,
        "user": {
            "id": user["id"],
            "username": user["username"],
            "name": user["name"],
            "is_admin": True,
        }
    })


@app.get("/admin/api/dashboard")
async def admin_dashboard(request: Request):
    """Dashboard stats."""
    require_admin(request)
    db.mark_stale_devices(HEARTBEAT_TIMEOUT)
    stats = db.get_dashboard_stats()
    stats["server_uptime"] = time.time() - SERVER_START_TIME
    return JSONResponse(content=stats)


@app.get("/admin/api/devices")
async def admin_devices(request: Request):
    """List all devices."""
    require_admin(request)
    db.mark_stale_devices(HEARTBEAT_TIMEOUT)
    devices = db.get_all_devices()
    result = []
    for d in devices:
        user = db.get_user_by_id(d["user_id"]) if d["user_id"] else None
        result.append({
            "id": d["id"],
            "uuid": d["uuid"],
            "hostname": d["hostname"],
            "os": d["os"],
            "version": d["version"],
            "cpu": d["cpu"],
            "memory": d["memory"],
            "ip": d["ip"],
            "status": d["status"],
            "last_heartbeat": d["last_heartbeat"],
            "first_seen": d["first_seen"],
            "user": user["username"] if user else None,
        })
    return JSONResponse(content={"devices": result})


@app.get("/admin/api/connections")
async def admin_connections(request: Request):
    """List connection audit logs (who connected to who)."""
    require_admin(request)
    limit = int(request.query_params.get("limit", 50))
    logs = db.get_connection_audit_logs(limit)
    result = []
    for log in logs:
        result.append({
            "id": log["id"],
            "timestamp": log["timestamp"],
            "action": log["action"],
            "source_id": log["source_id"],
            "source_ip": log["source_ip"],
            "target_id": log["target_id"],
            "target_ip": log["target_ip"],
            "duration": log["duration"],
            "note": log["note"],
        })
    return JSONResponse(content={"connections": result})





@app.get("/admin/api/audit")
async def admin_audit_logs(request: Request):
    """Get audit logs."""
    require_admin(request)
    limit = int(request.query_params.get("limit", 100))
    offset = int(request.query_params.get("offset", 0))
    action = request.query_params.get("action", None)
    logs = db.get_audit_logs(limit, offset, action)
    result = []
    for log in logs:
        result.append({
            "id": log["id"],
            "timestamp": log["timestamp"],
            "action": log["action"],
            "source_id": log["source_id"],
            "source_ip": log["source_ip"],
            "target_id": log["target_id"],
            "target_ip": log["target_ip"],
            "user_id": log["user_id"],
            "conn_id": log["conn_id"],
            "session_id": log["session_id"],
            "note": log["note"],
            "duration": log["duration"],
        })
    return JSONResponse(content={"logs": result})


@app.get("/admin/api/health")
async def admin_health(request: Request):
    """Get system health status for dashboard."""
    require_admin(request)
    return JSONResponse(content=GLOBAL_HEALTH)

@app.get("/admin/api/endpoints")
async def admin_get_endpoints(request: Request):
    """Get monitored endpoints (devices) with active connection status."""
    require_admin(request)
    endpoints = db.get_all_devices()
    active_conns = db.get_active_connections()
    
    # Create quick lookups
    device_names = {ep["id"]: (ep.get("custom_name") or ep.get("hostname") or ep["id"]) for ep in endpoints}
    busy_sources = {c["source_id"]: (c["target_id"], c.get("note", "")) for c in active_conns}
    busy_targets = {c["target_id"]: (c["source_id"], c.get("note", "")) for c in active_conns}
    
    type_map = {"0": "Desktop", "1": "File Transfer", "2": "RDP", "3": "Direct IP", "4": "RDP"}

    for ep in endpoints:
        ep_id = ep["id"]
        target_tuple = busy_sources.get(ep_id)
        source_tuple = busy_targets.get(ep_id)
        
        if target_tuple:
            target_id, raw_type = target_tuple
            ep["connected_to"] = target_id
            ep["connected_to_name"] = device_names.get(target_id, target_id)
            ep["connected_to_type"] = type_map.get(str(raw_type), raw_type or "Session")
        else:
            ep["connected_to"] = None
            ep["connected_to_name"] = None
            ep["connected_to_type"] = None
            
        if source_tuple:
            source_id, raw_type = source_tuple
            ep["connected_from"] = source_id
            ep["connected_from_name"] = device_names.get(source_id, source_id)
            ep["connected_from_type"] = type_map.get(str(raw_type), raw_type or "Session")
        else:
            ep["connected_from"] = None
            ep["connected_from_name"] = None
            ep["connected_from_type"] = None

    return JSONResponse(content={"endpoints": endpoints})

@app.post("/admin/api/endpoints/{device_id}")
async def admin_update_endpoint(device_id: str, request: Request):
    require_admin(request)
    body = await request.json()
    db.update_device_monitoring(
        device_id=device_id,
        custom_name=body.get("custom_name", ""),
        check_ping=1 if body.get("check_ping") else 0,
        check_rdp=1 if body.get("check_rdp") else 0,
        rdp_port=int(body.get("rdp_port", 3389) or 3389)
    )
    return JSONResponse(content={"success": True})


@app.get("/admin/api/logs")
async def admin_event_logs(request: Request):
    """Get in-memory event logs for dashboard."""
    require_admin(request)
    return JSONResponse(content={"logs": LOG_EVENTS[:100]})


# ─── WebSocket for live dashboard ───

@app.websocket("/ws/live")
async def websocket_live(websocket: WebSocket):
    """WebSocket endpoint for live dashboard updates."""
    await websocket.accept()
    ws_clients.add(websocket)
    try:
        # Send initial state
        db.mark_stale_devices(HEARTBEAT_TIMEOUT)
        stats = db.get_dashboard_stats()
        stats["server_uptime"] = time.time() - SERVER_START_TIME
        await websocket.send_text(json.dumps({"type": "stats", "data": stats}))

        # Send periodic updates
        while True:
            await asyncio.sleep(5)
            db.mark_stale_devices(HEARTBEAT_TIMEOUT)
            stats = db.get_dashboard_stats()
            stats["server_uptime"] = time.time() - SERVER_START_TIME

            devices = db.get_all_devices()
            device_list = [{
                "id": d["id"], "hostname": d["hostname"], "os": d["os"],
                "ip": d["ip"], "status": d["status"], "last_heartbeat": d["last_heartbeat"],
                "version": d["version"],
            } for d in devices]

            # Fetch endpoints and active connections for the websocket update
            endpoints = db.get_all_devices()
            active_conns = db.get_active_connections()
            device_names = {ep["id"]: (ep.get("custom_name") or ep.get("hostname") or ep["id"]) for ep in endpoints}
            busy_sources = {c["source_id"]: (c["target_id"], c.get("note", "")) for c in active_conns}
            busy_targets = {c["target_id"]: (c["source_id"], c.get("note", "")) for c in active_conns}
            type_map = {"0": "Desktop", "1": "File Transfer", "2": "RDP", "3": "Direct IP", "4": "RDP"}

            for ep in endpoints:
                ep_id = ep["id"]
                target_tuple = busy_sources.get(ep_id)
                source_tuple = busy_targets.get(ep_id)
                
                if target_tuple:
                    target_id, raw_type = target_tuple
                    ep["connected_to"] = target_id
                    ep["connected_to_name"] = device_names.get(target_id, target_id)
                    ep["connected_to_type"] = type_map.get(str(raw_type), raw_type or "Session")
                else:
                    ep["connected_to"] = None
                    ep["connected_to_name"] = None
                    ep["connected_to_type"] = None
                    
                if source_tuple:
                    source_id, raw_type = source_tuple
                    ep["connected_from"] = source_id
                    ep["connected_from_name"] = device_names.get(source_id, source_id)
                    ep["connected_from_type"] = type_map.get(str(raw_type), raw_type or "Session")
                else:
                    ep["connected_from"] = None
                    ep["connected_from_name"] = None
                    ep["connected_from_type"] = None

            await websocket.send_text(json.dumps({
                "type": "update",
                "stats": stats,
                "devices": device_list,
                "health": GLOBAL_HEALTH,
                "endpoints": endpoints
            }))
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        ws_clients.discard(websocket)


# ═══════════════════════════════════════════════════════════════════
# Frontend Serving
# ═══════════════════════════════════════════════════════════════════

@app.get("/")
@app.get("/admin")
@app.get("/admin/")
async def serve_admin():
    """Serve the admin dashboard index.html."""
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return HTMLResponse("<h1>Dashboard frontend not found</h1>", status_code=404)


@app.get("/styles.css")
async def serve_css():
    """Serve the dashboard CSS."""
    file_path = os.path.join(FRONTEND_DIR, "styles.css")
    if os.path.exists(file_path):
        return FileResponse(file_path, media_type="text/css")
    return HTMLResponse("Not found", status_code=404)


@app.get("/app.js")
async def serve_js():
    """Serve the dashboard JavaScript."""
    file_path = os.path.join(FRONTEND_DIR, "app.js")
    if os.path.exists(file_path):
        return FileResponse(file_path, media_type="application/javascript")
    return HTMLResponse("Not found", status_code=404)


@app.get("/admin/{path:path}")
async def serve_admin_static(path: str):
    """Serve admin static files."""
    file_path = os.path.join(FRONTEND_DIR, path)
    if os.path.exists(file_path) and os.path.isfile(file_path):
        return FileResponse(file_path)
    # Fall back to index.html for SPA routing
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return HTMLResponse("Not found", status_code=404)

