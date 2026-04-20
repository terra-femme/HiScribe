import logging
from datetime import datetime
from .sqlite import _conn

logger = logging.getLogger(__name__)


def save_enrollment(
    provider_id: str,
    name: str,
    encrypted_embedding: bytes,
    quality_score: float,
    sample_count: int,
) -> None:
    """
    Insert or replace a provider voice enrollment.
    Encrypted embedding is a Fernet-encrypted serialized numpy array.
    Replaces any existing record for the same provider_id.
    """
    now = datetime.utcnow().isoformat()
    with _conn() as conn:
        conn.execute(
            '''INSERT INTO provider_enrollments
               (provider_id, name, encrypted_embedding, quality_score, sample_count, enrolled_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(provider_id) DO UPDATE SET
                 name                = excluded.name,
                 encrypted_embedding = excluded.encrypted_embedding,
                 quality_score       = excluded.quality_score,
                 sample_count        = excluded.sample_count,
                 updated_at          = excluded.updated_at''',
            (provider_id, name, encrypted_embedding, quality_score, sample_count, now, now),
        )
    logger.info('[enrollment] Saved enrollment for provider_id=%s name=%s quality=%.3f samples=%d',
                provider_id, name, quality_score, sample_count)


def get_active_enrollments() -> list[dict]:
    """
    Return all enrolled providers. Includes encrypted_embedding bytes.
    Callers must decrypt before use.
    """
    with _conn() as conn:
        rows = conn.execute(
            'SELECT * FROM provider_enrollments ORDER BY enrolled_at ASC'
        ).fetchall()
    records = [dict(r) for r in rows]
    logger.debug('[enrollment] Loaded %d active enrollment(s)', len(records))
    return records


def get_enrollment(provider_id: str) -> dict | None:
    """
    Return a single enrollment record or None if not found.
    """
    with _conn() as conn:
        row = conn.execute(
            'SELECT * FROM provider_enrollments WHERE provider_id = ?',
            (provider_id,),
        ).fetchone()
    if row is None:
        logger.debug('[enrollment] No enrollment found for provider_id=%s', provider_id)
        return None
    return dict(row)


def delete_enrollment(provider_id: str) -> bool:
    """
    Delete an enrollment by provider_id.
    Returns True if a row was deleted, False if provider_id did not exist.
    """
    with _conn() as conn:
        cursor = conn.execute(
            'DELETE FROM provider_enrollments WHERE provider_id = ?',
            (provider_id,),
        )
        deleted = cursor.rowcount > 0
    if deleted:
        logger.info('[enrollment] Deleted enrollment for provider_id=%s', provider_id)
    else:
        logger.warning('[enrollment] Delete called for unknown provider_id=%s', provider_id)
    return deleted
