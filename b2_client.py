from b2sdk.v2 import InMemoryAccountInfo, B2Api
from config import B2_KEY_ID, B2_APPLICATION_KEY, B2_INSTALLERS_BUCKET_NAME, DOWNLOAD_URL_VALID_SECONDS

_info = InMemoryAccountInfo()
_api = B2Api(_info)
_authorized = False


def _ensure_authorized():
    global _authorized
    if not _authorized:
        _api.authorize_account("production", B2_KEY_ID, B2_APPLICATION_KEY)
        _authorized = True


# Maps what the frontend asks for to the actual filename in the bucket.
# Update these once you know your real built filenames (electron-builder's
# exact output name depends on your productName/version in package.json).
INSTALLER_FILENAMES = {
    "win": "Synora-setup.exe",
    "mac": "Synora.dmg",
}


def get_installer_download_url(platform: str) -> str:
    """Returns a short-lived, authorized download URL for the requested
    platform's installer. Raises ValueError for an unknown platform or
    KeyError-style bucket lookup failures bubble up as b2sdk exceptions."""
    if platform not in INSTALLER_FILENAMES:
        raise ValueError(f"Unknown platform: {platform}")

    filename = INSTALLER_FILENAMES[platform]

    _ensure_authorized()
    bucket = _api.get_bucket_by_name(B2_INSTALLERS_BUCKET_NAME)

    auth_token = bucket.get_download_authorization(
        file_name_prefix=filename,
        valid_duration_in_seconds=DOWNLOAD_URL_VALID_SECONDS,
    )
    base_url = bucket.get_download_url(filename)
    return f"{base_url}?Authorization={auth_token}"