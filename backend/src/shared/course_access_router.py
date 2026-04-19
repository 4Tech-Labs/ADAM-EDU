from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from shared.auth import CurrentActor, VerifiedIdentity, require_current_actor_password_ready, require_verified_identity
from shared.course_access import (
    CourseAccessActivateCompleteRequest,
    CourseAccessActivateCompleteResponse,
    CourseAccessActivateOAuthCompleteRequest,
    CourseAccessActivateOAuthCompleteResponse,
    CourseAccessActivatePasswordRequest,
    CourseAccessActivatePasswordResponse,
    CourseAccessEnrollRequest,
    CourseAccessEnrollResponse,
    CourseAccessResolveRequest,
    CourseAccessResolveResponse,
    activate_course_access_complete,
    activate_course_access_oauth_complete,
    activate_course_access_password,
    enroll_with_course_access,
    resolve_course_access,
)
from shared.database import get_db

router = APIRouter(prefix="/api/course-access", tags=["course-access"])


@router.post("/resolve", response_model=CourseAccessResolveResponse)
def post_course_access_resolve(
    request: CourseAccessResolveRequest,
    db: Session = Depends(get_db),
) -> CourseAccessResolveResponse:
    return resolve_course_access(db, request)


@router.post("/enroll", response_model=CourseAccessEnrollResponse)
def post_course_access_enroll(
    request: CourseAccessEnrollRequest,
    actor: Annotated[CurrentActor, Depends(require_current_actor_password_ready)],
    db: Session = Depends(get_db),
) -> CourseAccessEnrollResponse:
    return enroll_with_course_access(db, actor, request)


@router.post("/activate/password", response_model=CourseAccessActivatePasswordResponse, status_code=201)
def post_course_access_activate_password(
    request: CourseAccessActivatePasswordRequest,
    db: Session = Depends(get_db),
) -> CourseAccessActivatePasswordResponse:
    return activate_course_access_password(db, request)


@router.post("/activate/complete", response_model=CourseAccessActivateCompleteResponse)
def post_course_access_activate_complete(
    request: CourseAccessActivateCompleteRequest,
    identity: Annotated[VerifiedIdentity, Depends(require_verified_identity)],
    db: Session = Depends(get_db),
) -> CourseAccessActivateCompleteResponse:
    return activate_course_access_complete(db, identity, request)


@router.post("/activate/oauth/complete", response_model=CourseAccessActivateOAuthCompleteResponse)
def post_course_access_activate_oauth_complete(
    request: CourseAccessActivateOAuthCompleteRequest,
    identity: Annotated[VerifiedIdentity, Depends(require_verified_identity)],
    db: Session = Depends(get_db),
) -> CourseAccessActivateOAuthCompleteResponse:
    return activate_course_access_oauth_complete(db, identity, request)
