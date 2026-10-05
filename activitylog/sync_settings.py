"""Device-local sync preferences; credentials are stored separately with DPAPI."""

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import tempfile

from .sync import SyncError


@dataclass(frozen=True)
class SyncSettings:
    check_on_start: bool = True
    auto_sync: bool = False


class SyncSettingsStore:
    def __init__(self, directory):
        self.path = Path(directory) / "sync-settings.json" if directory else None

    def load(self):
        if self.path is None or not self.path.exists():
            return SyncSettings()
        try:
            values = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(values, dict) or set(values) != {"check_on_start", "auto_sync"}:
                raise ValueError()
            if any(type(value) is not bool for value in values.values()):
                raise ValueError()
            return SyncSettings(**values)
        except (OSError, ValueError, TypeError):
            raise SyncError("本机同步设置无法读取，自动同步已关闭；请重新设置。") from None

    def save(self, settings):
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.path.parent, mode="w", encoding="utf-8", delete=False) as file:
                temporary = Path(file.name)
                json.dump(asdict(settings), file, ensure_ascii=False)
            os.replace(temporary, self.path)
        finally:
            if temporary and temporary.exists():
                temporary.unlink()
