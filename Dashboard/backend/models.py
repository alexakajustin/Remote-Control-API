"""
Pydantic models for RustDesk API Server.
Models match the JSON payloads the RustDesk client sends/expects.
"""

from pydantic import BaseModel, Field
from typing import Optional, Any, List, Dict


# ─── Client Login ───

class LoginRequest(BaseModel):
    username: str = ""
    password: str = ""
    id: str = ""
    uuid: str = ""
    autoLogin: bool = False
    type: str = ""
    verificationCode: str = ""
    tfaCode: str = ""
    secret: str = ""
    deviceInfo: Optional[Dict[str, Any]] = None


class LoginResponse(BaseModel):
    access_token: str = ""
    type: str = "access_token"
    tfa_type: str = ""
    secret: str = ""
    user: Optional[Dict[str, Any]] = None


# ─── Heartbeat ───

class HeartbeatRequest(BaseModel):
    id: str = ""
    uuid: str = ""
    ver: int = 0
    modified_at: Optional[str] = None
    hostname: Optional[str] = None
    os: Optional[str] = None
    version: Optional[str] = None
    cpu: Optional[str] = None
    memory: Optional[str] = None
    language: Optional[str] = None
    username: Optional[str] = None
    ip: Optional[str] = None


# ─── System Info ───

class SysInfoRequest(BaseModel):
    id: str = ""
    uuid: str = ""
    hostname: str = ""
    username: str = ""
    os: str = ""
    version: str = ""
    cpu: str = ""
    memory: str = ""
    language: str = ""
    ip: str = ""


# ─── Current User ───

class CurrentUserRequest(BaseModel):
    id: str = ""
    uuid: str = ""


class UserInfo(BaseModel):
    name: str = ""
    email: str = ""
    login_device_info: Optional[str] = None
    note: str = ""
    status: int = 1
    is_admin: bool = False
    grp: str = ""


# ─── Address Book ───

class AddressBookRequest(BaseModel):
    data: Optional[str] = None
    # For personal ab
    ab: Optional[str] = None
    id: Optional[int] = None


class AddressBookPeer(BaseModel):
    id: str = ""
    username: str = ""
    hostname: str = ""
    alias: str = ""
    platform: str = ""
    tags: List[str] = Field(default_factory=list)
    forceAlwaysRelay: bool = False
    rdpPort: str = ""
    rdpUsername: str = ""
    loginName: str = ""
    hash: str = ""
    online: bool = False


class AddressBookPayload(BaseModel):
    tags: List[str] = Field(default_factory=list)
    peers: List[AddressBookPeer] = Field(default_factory=list)
    tag_colors: str = ""


# ─── Audit ───

class AuditRequest(BaseModel):
    action: str = ""
    id: str = ""
    Id: str = ""
    ip: str = ""
    uuid: str = ""
    conn_id: Optional[int] = None
    session_id: Optional[str] = None
    peer_id: Optional[str] = None
    note: Optional[str] = None
    from_id: Optional[str] = None
    from_ip: Optional[str] = None
    to_id: Optional[str] = None
    to_ip: Optional[str] = None


# ─── Admin Dashboard ───

class DashboardStats(BaseModel):
    total_devices: int = 0
    online_devices: int = 0
    total_users: int = 0
    connections_today: int = 0
    active_sessions: int = 0
    server_uptime: float = 0


class DeviceInfo(BaseModel):
    id: str = ""
    uuid: str = ""
    hostname: str = ""
    os: str = ""
    version: str = ""
    cpu: str = ""
    memory: str = ""
    ip: str = ""
    status: str = "offline"
    last_heartbeat: float = 0
    first_seen: float = 0
    user: Optional[str] = None


class ConnectionInfo(BaseModel):
    id: int = 0
    timestamp: float = 0
    action: str = ""
    source_id: str = ""
    source_ip: str = ""
    target_id: str = ""
    target_ip: str = ""
    duration: int = 0
    note: str = ""


class CreateUserRequest(BaseModel):
    username: str
    password: str
    name: str = ""
    email: str = ""
    is_admin: bool = False


class UpdateUserRequest(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    password: Optional[str] = None
    is_admin: Optional[bool] = None
    status: Optional[int] = None
