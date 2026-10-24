"""pause downloads if a bot check is unresolved

Revision ID: 6952e9785784
Revises: 594ab9c037ab
Create Date: 2026-10-25 01:00:09.828767

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '6952e9785784'
down_revision: Union[str, Sequence[str], None] = '594ab9c037ab'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Start paused when a bot-check alert is still unread, so deploying the circuit
    breaker doesn't fire one more request with cookies YouTube already rejected.
    The fingerprint is the current config, so only new cookies/proxy (or the
    Resume button) lift it."""
    from app.config import get_settings
    from app.services.downloader import config_fingerprint

    fp = config_fingerprint(get_settings())
    op.execute(
        sa.text(
            """
            INSERT INTO worker_status (id, staging_bytes, downloads_paused_reason,
                                       downloads_paused_at, paused_config_fp)
            SELECT 1, 0, 'YouTube bot check', now(), :fp
            WHERE EXISTS (SELECT 1 FROM alert WHERE kind = 'BOT_CHECK' AND read_at IS NULL)
               OR EXISTS (SELECT 1 FROM video WHERE download_status = 'NEW'
                          AND last_error ILIKE '%not a bot%')
            ON CONFLICT (id) DO UPDATE SET downloads_paused_reason = EXCLUDED.downloads_paused_reason,
                downloads_paused_at = EXCLUDED.downloads_paused_at,
                paused_config_fp = EXCLUDED.paused_config_fp
            """
        ).bindparams(fp=fp)
    )


def downgrade() -> None:
    """Downgrade schema."""
