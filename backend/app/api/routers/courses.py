"""``GET /api/courses``, ``GET /api/courses/{id}``, ``GET /api/courses/active``
— TASARIM.md §4, §8. ``/active`` frontend'in İLK YÜKLEMEDE aldığı snapshot'tır
(İlke 4: "Event sourcing + snapshot") — ``v_active_course_state`` view'inden
TEK sorguyla okunur.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.schemas import ActiveCourseOut, ActiveCourseSlotOut, CourseDetailOut, CourseOut, CourseSlotOut
from app.db.models import ActiveCourseStateRow, CourseSlot, RollingCourse

router = APIRouter(prefix="/api/courses", tags=["courses"])


@router.get("", response_model=list[CourseOut])
def list_courses(
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[RollingCourse]:
    stmt = select(RollingCourse).order_by(RollingCourse.course_number.desc())
    if status is not None:
        stmt = stmt.where(RollingCourse.status == status)
    stmt = stmt.offset(offset).limit(limit)
    return list(db.execute(stmt).scalars().all())


@router.get("/active", response_model=ActiveCourseOut | None)
def get_active_course(db: Session = Depends(get_db)) -> ActiveCourseOut | None:
    rows = list(
        db.execute(
            select(ActiveCourseStateRow).order_by(ActiveCourseStateRow.position_index)
        ).scalars().all()
    )
    if not rows:
        return None
    head = rows[0]
    slots = [r for r in rows if r.position_index is not None]
    return ActiveCourseOut(
        course_id=head.course_id,
        course_number=head.course_number,
        status=head.status,
        order_count=head.order_count,
        current_length_mm=head.current_length_mm,
        reverse_width_events_count=head.reverse_width_events_count,
        slots=[ActiveCourseSlotOut.model_validate(r) for r in slots],
    )


@router.get("/{course_id}", response_model=CourseDetailOut)
def get_course(course_id: int, db: Session = Depends(get_db)) -> CourseDetailOut:
    course = db.get(RollingCourse, course_id)
    if course is None:
        raise HTTPException(status_code=404, detail=f"rolling_courses.id={course_id} bulunamadı")
    slots = list(
        db.execute(
            select(CourseSlot).where(CourseSlot.course_id == course_id).order_by(CourseSlot.position_index)
        ).scalars().all()
    )
    return CourseDetailOut(
        **CourseOut.model_validate(course).model_dump(),
        slots=[CourseSlotOut.model_validate(s) for s in slots],
    )
