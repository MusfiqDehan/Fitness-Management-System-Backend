from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BiometricDeviceProfile:
    key: str
    label: str
    manufacturer: str
    supports_remote_enroll: bool
    max_users: int
    max_fingers_per_user: int
    push_trans_flag: str
    remote_enroll_command_template: str

    def build_userinfo_command(self, *, pin: str, name: str) -> str:
        safe_name = (name or "").replace("\t", " ").strip()[:40]
        return (
            f"DATA UPDATE USERINFO PIN={pin}\t"
            f"Name={safe_name}\t"
            f"Pri=0\t"
            f"Passwd=\t"
            f"Card=\t"
            f"Grp=1\t"
            f"TZ=0000000100000000\t"
            f"Verify=-1"
        )

    def build_remote_enroll_command(self, *, pin: str, fingerprint_slot: int = 0) -> str:
        return self.remote_enroll_command_template.format(
            pin=pin,
            fid=fingerprint_slot,
        )


_DEFAULT_TRANS_FLAG = "111111111111"
_REMOTE_ENROLL_TEMPLATE = "ENROLL_FP PIN={pin}\tFID={fid}"


DEVICE_PROFILES: dict[str, BiometricDeviceProfile] = {
    "zkteco_f18": BiometricDeviceProfile(
        key="zkteco_f18",
        label="ZKTeco F18",
        manufacturer="ZKTeco",
        supports_remote_enroll=True,
        max_users=3000,
        max_fingers_per_user=10,
        push_trans_flag=_DEFAULT_TRANS_FLAG,
        remote_enroll_command_template=_REMOTE_ENROLL_TEMPLATE,
    ),
    "zkteco_f18_pro": BiometricDeviceProfile(
        key="zkteco_f18_pro",
        label="ZKTeco F18 Pro",
        manufacturer="ZKTeco",
        supports_remote_enroll=True,
        max_users=3000,
        max_fingers_per_user=10,
        push_trans_flag=_DEFAULT_TRANS_FLAG,
        remote_enroll_command_template=_REMOTE_ENROLL_TEMPLATE,
    ),
    "zkteco_k40": BiometricDeviceProfile(
        key="zkteco_k40",
        label="ZKTeco K40",
        manufacturer="ZKTeco",
        supports_remote_enroll=True,
        max_users=3000,
        max_fingers_per_user=10,
        push_trans_flag=_DEFAULT_TRANS_FLAG,
        remote_enroll_command_template=_REMOTE_ENROLL_TEMPLATE,
    ),
    "zkteco_k60": BiometricDeviceProfile(
        key="zkteco_k60",
        label="ZKTeco K60",
        manufacturer="ZKTeco",
        supports_remote_enroll=True,
        max_users=3000,
        max_fingers_per_user=10,
        push_trans_flag=_DEFAULT_TRANS_FLAG,
        remote_enroll_command_template=_REMOTE_ENROLL_TEMPLATE,
    ),
}

DEFAULT_DEVICE_PROFILE_KEY = "zkteco_f18"


def get_device_profile(key: str | None) -> BiometricDeviceProfile:
    normalized = (key or DEFAULT_DEVICE_PROFILE_KEY).strip()
    profile = DEVICE_PROFILES.get(normalized)
    if profile is None:
        raise ValueError(f"Unknown device profile: {normalized}")
    return profile


def list_device_profiles() -> list[BiometricDeviceProfile]:
    return list(DEVICE_PROFILES.values())


def is_valid_device_profile(key: str | None) -> bool:
    if not key:
        return False
    return key.strip() in DEVICE_PROFILES
