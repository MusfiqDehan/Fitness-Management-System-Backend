from __future__ import annotations

from datetime import timedelta

from django.utils import timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apps.attendance.device_profiles import BiometricDeviceProfile, get_device_profile
from apps.attendance.models import AccessDevice, AttendanceIngestEvent


def _next_command_id(device: AccessDevice) -> int:
    meta = dict(device.meta_json or {})
    current = int(meta.get("command_id_seq", 0))
    next_id = current + 1
    meta["command_id_seq"] = next_id
    device.meta_json = meta
    return next_id


def get_pending_commands(device: AccessDevice) -> list[dict]:
    meta = dict(device.meta_json or {})
    return list(meta.get("pending_commands", []))


def queue_commands(device: AccessDevice, commands: list[str], *, session_id: int | None = None) -> list[dict]:
    """Append ADMS commands to device pending queue."""
    meta = dict(device.meta_json or {})
    pending = list(meta.get("pending_commands", []))
    command_index = dict(meta.get("command_index", {}))
    queued: list[dict] = []

    for cmd in commands:
        cmd_id = _next_command_id(device)
        entry = {"id": cmd_id, "cmd": cmd}
        if session_id is not None:
            entry["session_id"] = session_id
        pending.append(entry)
        command_index[str(cmd_id)] = entry
        queued.append(entry)

    meta["pending_commands"] = pending
    meta["command_index"] = command_index
    device.meta_json = meta
    device.save(update_fields=["meta_json", "updated_at"])
    return queued


def dequeue_next_command(device: AccessDevice) -> dict | None:
    meta = dict(device.meta_json or {})
    pending = list(meta.get("pending_commands", []))
    if not pending:
        return None
    next_cmd = pending.pop(0)
    meta["pending_commands"] = pending
    meta["last_command_sent"] = next_cmd["cmd"]
    meta["last_command_sent_at"] = timezone.now().isoformat()
    meta["last_command_sent_id"] = next_cmd["id"]
    device.meta_json = meta
    return next_cmd


def build_userinfo_command(
    profile: BiometricDeviceProfile,
    *,
    pin: str,
    name: str,
    card: str = "",
) -> str:
    return profile.build_userinfo_command(pin=pin, name=name, card=card)


def build_remote_enroll_command(
    profile: BiometricDeviceProfile,
    *,
    pin: str,
    fingerprint_slot: int = 0,
) -> str:
    return profile.build_remote_enroll_command(pin=pin, fingerprint_slot=fingerprint_slot)


def build_attlog_sync_command(device: AccessDevice) -> tuple[str, str]:
    try:
        device_tz = ZoneInfo(device.timezone or "Asia/Dhaka")
    except ZoneInfoNotFoundError:
        device_tz = ZoneInfo("UTC")

    latest_attlog = (
        AttendanceIngestEvent.objects.filter(
            access_device=device,
            event_type="ATTLOG",
            event_time__isnull=False,
        )
        .order_by("-event_time")
        .first()
    )

    if latest_attlog and latest_attlog.event_time:
        start_time = latest_attlog.event_time.astimezone(device_tz) - timedelta(minutes=1)
    else:
        start_time = timezone.now().astimezone(device_tz) - timedelta(minutes=5)

    formatted = start_time.strftime("%Y-%m-%d %H:%M:%S")
    return f"DATA QUERY ATTLOG StartTime={formatted}", formatted


def build_push_handshake_body(device: AccessDevice) -> str:
    profile = get_device_profile(device.device_profile)
    try:
        tz = ZoneInfo(device.timezone or "Asia/Dhaka")
    except ZoneInfoNotFoundError:
        tz = ZoneInfo("UTC")
    offset = timezone.now().astimezone(tz).utcoffset()
    hours = int(offset.total_seconds() // 3600) if offset else 0
    return (
        f"GET OPTION FROM: {device.device_sn}\n"
        "ATTLOGStamp=0\n"
        "OPERLOGStamp=0\n"
        "USERINFOStamp=0\n"
        "BIODATAStamp=0\n"
        "ATTPHOTOStamp=0\n"
        "ErrorDelay=30\n"
        "Delay=5\n"
        "Realtime=1\n"
        "ServerVer=3.0.1\n"
        "PushProtVer=2.4.1\n"
        f"TransFlag={profile.push_trans_flag}\n"
        f"TimeZone={hours}\n"
    )


def parse_devicecmd_body(raw: str) -> dict:
    """Parse devicecmd POST body: ID=3&Return=0&CMD=DATA"""
    out: dict[str, str] = {}
    for part in (raw or "").split("&"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        out[key.strip()] = value.strip()
    return out


def lookup_queued_command(device: AccessDevice, command_id: str) -> dict | None:
    meta = dict(device.meta_json or {})
    command_index = meta.get("command_index", {})
    entry = command_index.get(str(command_id))
    if entry:
        return entry
    for item in meta.get("pending_commands", []):
        if str(item.get("id")) == str(command_id):
            return item
    last_id = meta.get("last_command_sent_id")
    if last_id is not None and str(last_id) == str(command_id):
        return {
            "id": last_id,
            "cmd": meta.get("last_command_sent", ""),
            "session_id": meta.get("last_command_session_id"),
        }
    return None
