"""Persist the Quiz Cleaner library on a private Hugging Face dataset.

HF Spaces' default disk is ephemeral. To survive restarts on the free CPU
Basic tier we mirror the library directory to a private HF dataset:

  - On Space startup we download the dataset into the local STORAGE_ROOT,
    rebuilding the library exactly as it was before.
  - After each confirm() in the quiz API we push that one library entry up.
  - After each delete() we remove the corresponding remote folder.

Sync is OFF unless both ``HF_DATASET_REPO`` and ``HF_TOKEN`` env vars are set,
so local development behaves exactly as before.
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Lazy import of huggingface_hub - only needed when sync is enabled.
_HF_API = None
_HF_AVAILABLE = False
try:  # pragma: no cover - import-time best effort
    from huggingface_hub import HfApi  # type: ignore
    from huggingface_hub.utils import HfHubHTTPError  # type: ignore

    _HF_AVAILABLE = True
except Exception as exc:  # noqa: BLE001
    logger.info("huggingface_hub not importable; HF storage sync disabled (%s)", exc)


def is_enabled() -> bool:
    """True when HF dataset sync should run."""
    if not _HF_AVAILABLE:
        return False
    return bool(os.environ.get("HF_DATASET_REPO")) and bool(os.environ.get("HF_TOKEN"))


def _repo() -> str:
    return os.environ["HF_DATASET_REPO"].strip()


def _api() -> "HfApi":
    global _HF_API
    if _HF_API is None:
        _HF_API = HfApi(token=os.environ["HF_TOKEN"].strip())
    return _HF_API


def ensure_repo() -> None:
    """Create the dataset on first use if it doesn't already exist."""
    if not is_enabled():
        return
    try:
        _api().create_repo(
            repo_id=_repo(),
            repo_type="dataset",
            private=True,
            exist_ok=True,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("HF sync: ensure_repo failed: %s", exc)


def restore_on_startup(local_dir: Path) -> None:
    """Pull the entire dataset into ``local_dir`` so the library is restored.

    Safe to call when the dataset is empty or the network is down.
    """
    if not is_enabled():
        return
    try:
        from huggingface_hub import snapshot_download  # local import
    except Exception as exc:  # noqa: BLE001
        logger.warning("HF sync: snapshot_download import failed: %s", exc)
        return

    local_dir.mkdir(parents=True, exist_ok=True)
    try:
        ensure_repo()
        snapshot_download(
            repo_id=_repo(),
            repo_type="dataset",
            local_dir=str(local_dir),
            token=os.environ["HF_TOKEN"].strip(),
        )
        logger.info("HF sync: restored library from %s into %s", _repo(), local_dir)
    except HfHubHTTPError as exc:
        # Empty dataset (404) or auth issue. Auth issues we want to surface.
        if "401" in str(exc) or "403" in str(exc):
            logger.error("HF sync: auth failed restoring library: %s", exc)
        else:
            logger.info("HF sync: nothing to restore yet (%s)", exc)
    except Exception as exc:  # noqa: BLE001
        logger.warning("HF sync: restore_on_startup failed: %s", exc)


def upload_entry(local_folder: Path, remote_subpath: str) -> None:
    """Push one library entry folder up to the dataset.

    Runs synchronously on the request thread - it is small (one PDF + one
    JSON) so this is fine for our 2-user workload. Failures are logged but
    do NOT raise, so a network blip never loses the local copy.
    """
    if not is_enabled():
        return
    try:
        ensure_repo()
        _api().upload_folder(
            folder_path=str(local_folder),
            path_in_repo=remote_subpath,
            repo_id=_repo(),
            repo_type="dataset",
            commit_message=f"sync {remote_subpath}",
        )
        logger.info("HF sync: uploaded %s -> %s", local_folder, remote_subpath)
    except Exception as exc:  # noqa: BLE001
        logger.warning("HF sync: upload_entry %s failed: %s", remote_subpath, exc)


def upload_entry_async(local_folder: Path, remote_subpath: str) -> None:
    """Fire-and-forget version, so the user's HTTP response is not blocked
    by a slow upload."""
    if not is_enabled():
        return
    threading.Thread(
        target=upload_entry,
        args=(Path(local_folder), remote_subpath),
        daemon=True,
        name=f"hf-sync-upload-{remote_subpath}",
    ).start()


def delete_entry(remote_subpath: str) -> None:
    """Remove a folder from the dataset (matches a local delete)."""
    if not is_enabled():
        return
    try:
        _api().delete_folder(
            path_in_repo=remote_subpath,
            repo_id=_repo(),
            repo_type="dataset",
            commit_message=f"delete {remote_subpath}",
        )
        logger.info("HF sync: deleted %s", remote_subpath)
    except Exception as exc:  # noqa: BLE001
        logger.warning("HF sync: delete_entry %s failed: %s", remote_subpath, exc)


def delete_entry_async(remote_subpath: str) -> None:
    if not is_enabled():
        return
    threading.Thread(
        target=delete_entry,
        args=(remote_subpath,),
        daemon=True,
        name=f"hf-sync-delete-{remote_subpath}",
    ).start()
