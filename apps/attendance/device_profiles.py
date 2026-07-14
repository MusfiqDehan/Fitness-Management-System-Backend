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
_STELLAR_STUB_TEMPLATE = "STELLAR_ENROLL_UNSUPPORTED PIN={pin}\tFID={fid}"


DEVICE_PROFILES: dict[str, BiometricDeviceProfile] = {
    "zkteco": BiometricDeviceProfile(
        key="zkteco",
        label="ZKTeco",
        manufacturer="ZKTeco",
        supports_remote_enroll=True,
        max_users=3000,
        max_fingers_per_user=10,
        push_trans_flag=_DEFAULT_TRANS_FLAG,
        remote_enroll_command_template=_REMOTE_ENROLL_TEMPLATE,
    ),
    "stellar": BiometricDeviceProfile(
        key="stellar",
        label="Stellar",
        manufacturer="Stellar",
        supports_remote_enroll=False,
        max_users=0,
        max_fingers_per_user=0,
        push_trans_flag="",
        remote_enroll_command_template=_STELLAR_STUB_TEMPLATE,
    ),
}

DEFAULT_DEVICE_PROFILE_KEY = "zkteco"

# Legacy per-model keys → (profile, device_model) for data migration only.
LEGACY_ZKTECO_PROFILE_MAP: dict[str, tuple[str, str]] = {
    "zkteco_f18": ("zkteco", "F18"),
    "zkteco_f18_pro": ("zkteco", "F18 Pro"),
    "zkteco_k40": ("zkteco", "K40"),
    "zkteco_k60": ("zkteco", "K60"),
}


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
