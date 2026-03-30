import json
import os
import uuid
from datetime import datetime

REGISTRY_FILE = "moved_files_registry.json"

class RegistryManager:
    def __init__(self):
        self.file_path = REGISTRY_FILE
        self._ensure_file()

    def _ensure_file(self):
        if not os.path.exists(self.file_path):
            with open(self.file_path, 'w', encoding='utf-8') as f:
                json.dump([], f)

    def load_registry(self):
        try:
            with open(self.file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return []

    def save_registry(self, data):
        with open(self.file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

    def add_entry(self, original_path, d_drive_path, size_bytes):
        data = self.load_registry()
        entry = {
            "id": str(uuid.uuid4()),
            "original_path": original_path,
            "d_drive_path": d_drive_path,
            "size_bytes": size_bytes,
            "moved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        data.append(entry)
        self.save_registry(data)
        return entry

    def remove_entry(self, entry_id):
        data = self.load_registry()
        data = [e for e in data if e['id'] != entry_id]
        self.save_registry(data)
