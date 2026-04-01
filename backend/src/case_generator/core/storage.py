import os
from typing import Protocol, Optional
from datetime import datetime

class IStorageProvider(Protocol):
    """
    Abstract interface for artifact storage providers.
    """
    async def upload_text(self, text_content: str, assignment_id: str, job_id: str, artifact_type: str, version: int) -> str:
        ...

class LocalStorageProvider:
    """
    Local storage provider used by development and test environments.
    Saves artifacts under `.data/mock_gcs`.
    """
    def __init__(self, base_path: str = ".data/mock_gcs"):
        self.base_path = base_path
        os.makedirs(self.base_path, exist_ok=True)

    async def upload_text(self, text_content: str, assignment_id: str, job_id: str, artifact_type: str, version: int) -> str:
        """
        Persist text content locally using deterministic authoring artifact paths.
        """
        # Create deterministic path: base_path/assignment_id/job_id/
        dir_path = os.path.join(self.base_path, assignment_id, job_id)
        os.makedirs(dir_path, exist_ok=True)
        
        # Determine file extension
        ext = ".json" if text_content.strip().startswith("{") or text_content.strip().startswith("[") else ".md"
        
        # File name: v{version}_{artifact_type}{ext}
        file_name = f"v{version}_{artifact_type}{ext}"
        file_path = os.path.join(dir_path, file_name)
        
        with open(file_path, mode='w', encoding='utf-8') as f:
            f.write(text_content)
            
        # Return a local URI that mimics object-storage addressing.
        return f"local://{file_path}"

# Swappable seam for future storage backends.
def get_storage_provider() -> IStorageProvider:
    # The current MVP uses local storage by default.
    return LocalStorageProvider()
