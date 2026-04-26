# backend/gcs_utils.py
"""Minimal GCS helpers for per-user artifact storage and signed URLs.

Uses Application Default Credentials (ADC) + SA impersonation for signing.

Production story:
- GKE pods run as a runtime service account (via Workload Identity).
- That runtime SA is allowed to impersonate a dedicated signer SA.
- The signer SA has least-privilege access to the artifact bucket.
- No JSON keys are baked into images or mounted into pods.

Usage pattern:
    from backend.gcs_utils import upload_bytes, sign_url, get_bucket_name
    upload_bytes(bucket, path, data, content_type="audio/mpeg")
    url = sign_url(bucket, path)
"""

from __future__ import annotations

import datetime as dt
import logging
import os

import google.auth
from google.auth import impersonated_credentials
from google.cloud import storage

# Import to trigger app-level logging configuration (handlers, format, level).
from backend.utils import app_logging  # noqa: F401

logger = logging.getLogger(f"app.{__name__}")

_storage_client: storage.Client | None = None


def _client() -> storage.Client:
    """Return a cached Storage client using ADC (GKE Workload Identity or local ADC)."""
    global _storage_client
    if _storage_client is None:
        _storage_client = storage.Client()  # Uses google.auth.default()
    return _storage_client


def upload_bytes(bucket: str, path: str, data: bytes, content_type: str) -> str:
    """Upload bytes to gs://bucket/path and return the gs:// path.

    Does NOT make the object public - use sign_url() to get access URLs.
    Returns the gs:// path for reference (not a usable URL).
    """
    b = _client().bucket(bucket)
    blob = b.blob(path)
    blob.upload_from_string(data, content_type=content_type)
    logger.info("GCS upload success: gs://%s/%s (%d bytes)", bucket, path, len(data))
    return f"gs://{bucket}/{path}"


def sign_url(bucket: str, path: str, minutes: int = 60) -> str:
    """Return a V4 signed URL for the given object.

    Security model:
    - In GKE: pod runs as a runtime SA via Workload Identity (ambient ADC).
    - We use that runtime SA as the *source* to impersonate a dedicated signer SA.
    - The signer SA has storage access on the artifact bucket and can sign URLs.
    - No JSON keys are present in the container.

    Locally:
    - ADC must be able to impersonate the signer SA (e.g. your dev identity
      has roles/iam.serviceAccountTokenCreator on the signer SA), OR
    - You can point GOOGLE_APPLICATION_CREDENTIALS to a SA that has that role.
    """
    client = _client()
    blob = client.bucket(bucket).blob(path)

    # 1. Ambient ADC: this is the runtime SA in GKE, or your local identity.
    source_creds, project_id = google.auth.default()

    signer_service_account = os.getenv("GCS_SIGNER_SERVICE_ACCOUNT")
    if not signer_service_account:
        raise RuntimeError(
            "GCS_SIGNER_SERVICE_ACCOUNT is not configured. "
            "Set the env var GCS_SIGNER_SERVICE_ACCOUNT to the signer SA email, "
            "e.g. gcs-signer@your-project.iam.gserviceaccount.com."
        )

    # 2. Impersonate the dedicated signer SA.
    signing_creds = impersonated_credentials.Credentials(
        source_credentials=source_creds,
        target_principal=signer_service_account,
        # Minimal scope needed to read objects; signing is handled via IAM.
        target_scopes=["https://www.googleapis.com/auth/devstorage.read_only"],
        lifetime=300,  # short-lived token
    )

    # 3. Use impersonated creds to generate the signed URL (V4).
    if not blob.exists():
        logger.error("Object does not exist: gs://%s/%s", bucket, path)
        raise FileNotFoundError(f"GCS object not found: gs://{bucket}/{path}")
    try:
        url = blob.generate_signed_url(
            version="v4",
            expiration=dt.timedelta(minutes=minutes),
            method="GET",
            credentials=signing_creds,
        )
        return url
    except Exception as e:
        logger.error(
            "Failed to generate signed URL for gs://%s/%s via signer SA %s: %s",
            bucket,
            path,
            signer_service_account,
            e,
        )
        raise


def get_bucket_name() -> str:
    """Return artifact bucket name.

    Prefer GCS_ARTIFACT_BUCKET when set to avoid conflicts with other buckets
    (e.g., a RAG bucket).
    """
    return os.environ.get("GCS_ARTIFACT_BUCKET")


def object_exists(bucket: str, path: str) -> bool:
    """Check if object exists in GCS."""
    b = _client().bucket(bucket)
    blob = b.blob(path)
    return blob.exists()


def download_bytes(bucket: str, path: str) -> bytes:
    """Download object bytes from GCS."""
    b = _client().bucket(bucket)
    blob = b.blob(path)
    return blob.download_as_bytes()


def delete_folder(bucket: str, prefix: str) -> int:
    """Delete all objects with the given prefix (folder) from GCS.

    Also handles folder placeholder objects (empty objects ending with /).
    Returns the number of objects deleted.
    """
    b = _client().bucket(bucket)

    # List and delete all objects with this prefix
    blobs = list(b.list_blobs(prefix=prefix))
    count = 0
    for blob in blobs:
        logger.debug("Deleting GCS object: gs://%s/%s", bucket, blob.name)
        blob.delete()
        count += 1

    # Try to delete folder placeholder objects
    folder_paths = [
        prefix,  # e.g., "userId/"
        prefix.rstrip("/"),  # e.g., "userId"
    ]

    for folder_path in folder_paths:
        try:
            folder_blob = b.blob(folder_path)
            if folder_blob.exists():
                logger.debug("Deleting folder placeholder: gs://%s/%s", bucket, folder_path)
                folder_blob.delete()
                count += 1
        except Exception as e:
            logger.debug("No folder placeholder at gs://%s/%s: %s", bucket, folder_path, e)

    if count > 0:
        logger.info("GCS deleted %d objects with prefix gs://%s/%s", count, bucket, prefix)
    else:
        logger.info("No GCS objects found with prefix gs://%s/%s", bucket, prefix)

    return count
