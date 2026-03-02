"""
claim_manager.py — Atomic claim-by-move for vault action files (Platinum Tier).

Uses os.rename() (atomic on same filesystem) to claim items from a source
directory to a destination directory. If another agent already moved the file
the rename raises FileNotFoundError — the caller should skip and continue.

Never use copy+delete: only rename ensures atomicity.

Usage:
    cm = ClaimManager(
        source=vault / "Needs_Action/cloud",
        destination=vault / "In_Progress/cloud",
    )
    item = cm.claim_next()
    if item:
        # process item ...
        cm.release(item, done_dir=vault / "Done")
    else:
        # nothing to claim
        pass
"""

import logging
import os
from pathlib import Path

logger = logging.getLogger("cloud.claim_manager")


class ClaimManager:
    """
    Atomic claim-by-move for action files.

    claim_next()   — move the oldest .md file from source → destination
    release()      — move a claimed file to done_dir after processing
    release_error()— move a claimed file back to source (or error dir)
    """

    def __init__(self, source: Path, destination: Path):
        self.source = source
        self.destination = destination
        destination.mkdir(parents=True, exist_ok=True)

    def _candidates(self) -> list[Path]:
        """Return .md files in source, sorted oldest-first (FIFO)."""
        if not self.source.exists():
            return []
        files = [
            f for f in self.source.iterdir()
            if f.suffix == ".md" and not f.name.startswith(".")
        ]
        return sorted(files, key=lambda f: f.stat().st_mtime)

    def claim_next(self) -> Path | None:
        """
        Atomically move the oldest .md file from source → destination.
        Returns the new path in destination, or None if nothing to claim.

        If another agent already moved the file (FileNotFoundError), skip it
        and try the next candidate.
        """
        for candidate in self._candidates():
            target = self.destination / candidate.name
            try:
                os.rename(candidate, target)
                logger.info(f"Claimed: {candidate.name} → {self.destination.name}/")
                return target
            except FileNotFoundError:
                logger.debug(f"Race: {candidate.name} already claimed by another agent")
                continue
            except OSError as err:
                logger.error(f"Claim failed for {candidate.name}: {err}")
                continue
        return None

    def claim_all(self) -> list[Path]:
        """Claim all available items and return list of claimed paths."""
        claimed = []
        while True:
            item = self.claim_next()
            if item is None:
                break
            claimed.append(item)
        return claimed

    def release(self, item: Path, done_dir: Path) -> Path:
        """
        Move a successfully-processed item to done_dir.
        Returns the new path in done_dir.
        """
        done_dir.mkdir(parents=True, exist_ok=True)
        target = done_dir / item.name
        os.rename(item, target)
        logger.info(f"Released to Done: {item.name}")
        return target

    def release_error(self, item: Path, error_dir: Path | None = None) -> Path:
        """
        Move a failed item back to source (or error_dir if provided).
        Returns the new path.
        """
        dest = error_dir or self.source
        dest.mkdir(parents=True, exist_ok=True)
        target = dest / item.name
        try:
            os.rename(item, target)
            logger.warning(f"Returned {item.name} to {dest.name}/ after error")
        except OSError as err:
            logger.error(f"Failed to release_error {item.name}: {err}")
        return target
