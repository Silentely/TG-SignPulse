"""Re-export of tg_signer.core.peer_resolver for top-level access."""

from tg_signer.core.peer_resolver import (
    _WARM_FLAG,
    DEFAULT_DIALOG_LIMIT,
    PeerResolution,
    PeerResolveError,
    candidate_ids,
    resolve_peer_id,
    warm_peer_cache,
)

__all__ = [
    "DEFAULT_DIALOG_LIMIT",
    "_WARM_FLAG",
    "PeerResolution",
    "PeerResolveError",
    "candidate_ids",
    "resolve_peer_id",
    "warm_peer_cache",
]
