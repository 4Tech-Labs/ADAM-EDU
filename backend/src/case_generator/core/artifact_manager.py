import logging
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified
from shared.models import ArtifactManifest, AuthoringJob
from case_generator.core.storage import IStorageProvider

logger = logging.getLogger(__name__)

class ArtifactManager:
    """
    Manages ArtifactManifest rows and deterministic artifact persistence.
    The persisted status names are retained for compatibility with the current schema.
    """

    @classmethod
    async def save_artifact(
        cls, 
        db: Session, 
        storage_provider: IStorageProvider,
        text_content: str, 
        assignment_id: str, 
        job_id: str, 
        owner_id: str, 
        artifact_type: str, 
        producer_node: str,
        version: int = 1
    ) -> str:
        """
        Idempotent operation that uploads an artifact to storage and creates or
        updates the matching ArtifactManifest row.
        
        Consistency Policy (Storage OK + DB Fail):
        -------------------------------------------
        Storage uses a DETERMINISTIC path: {assignment_id}/{job_id}/v{version}_{artifact_type}.ext
        This means a subsequent retry will overwrite the exact same blob at the same path.
        If the DB insert/upsert fails AFTER storage upload succeeds:
          1. The orphaned blob remains in storage (harmless: same deterministic path).
          2. The exception propagates to AuthoringService, which marks the job as 'failed'.
          3. On retry, save_artifact overwrites the blob AND creates/updates the manifest row.
        This is a "deterministic overwrite on retry" policy: no stale blobs accumulate,
        and the DB remains the sole source of truth for manifest existence.
        
        Returns the artifact_manifest_id (UUID).
        """
        
        # Storage upload uses a deterministic path and is safe to overwrite on retry.
        uri = await storage_provider.upload_text(
            text_content=text_content, 
            assignment_id=assignment_id, 
            job_id=job_id, 
            artifact_type=artifact_type, 
            version=version
        )
        
        # DB upsert may fail independently; retries safely overwrite the same blob path.
        try:
            existing_manifest = db.query(ArtifactManifest).filter(
                ArtifactManifest.assignment_id == assignment_id,
                ArtifactManifest.job_id == job_id,
                ArtifactManifest.artifact_type == artifact_type,
                ArtifactManifest.producer_node == producer_node
            ).first()
        
            if existing_manifest:
                logger.info(f"ArtifactManager: Overwriting existing manifest {existing_manifest.id} ({artifact_type})")
                existing_manifest.gcs_uri = uri
                existing_manifest.version = version
                existing_manifest.status = "unvalidated"
                db.commit()
                db.refresh(existing_manifest)
                return existing_manifest.id
            else:
                logger.info(f"ArtifactManager: Creating new manifest for {artifact_type}")
                new_manifest = ArtifactManifest(
                    assignment_id=assignment_id,
                    job_id=job_id,
                    owner_id=owner_id,
                    artifact_type=artifact_type,
                    producer_node=producer_node,
                    version=version,
                    gcs_uri=uri,
                    status="unvalidated"
                )
                db.add(new_manifest)
                db.commit()
                db.refresh(new_manifest)
                return new_manifest.id
        except Exception as e:
            db.rollback()
            logger.error(
                f"ArtifactManager: DB write failed for {artifact_type} after successful storage upload "
                f"(URI: {uri}). Blob is safe at deterministic path and will be overwritten on retry. "
                f"Error: {e}"
            )
            raise

    @classmethod
    def orphan_job_artifacts(cls, db: Session, job_id: str) -> None:
        """
        Mark unvalidated manifests as orphaned when a job fails.
        """
        manifests = db.query(ArtifactManifest).filter(
            ArtifactManifest.job_id == job_id,
            ArtifactManifest.status == "unvalidated"
        ).all()
        
        for m in manifests:
            m.status = "orphaned"
            
        if manifests:
            logger.info(f"ArtifactManager: Marked {len(manifests)} manifests as 'orphaned' for failed Job {job_id}")
            db.commit()
            
    @classmethod
    def publish_job_artifacts(cls, db: Session, job_id: str) -> None:
        """
        Promote unvalidated artifacts to the persisted `published_v5` status.
        """
        manifests = db.query(ArtifactManifest).filter(
            ArtifactManifest.job_id == job_id,
            ArtifactManifest.status == "unvalidated"
        ).all()
        
        for m in manifests:
            m.status = "published_v5"
            
        if manifests:
            logger.info(f"ArtifactManager: Promoted {len(manifests)} manifests to 'published_v5' for Job {job_id}")
            db.commit()


