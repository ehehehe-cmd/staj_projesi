"""``api/routers/courses.py`` testleri — TASARIM.md §4, §8, §12.7."""

from __future__ import annotations

from app.core.constraints import RollingConstraints
from app.db import crud


def _constraints(**overrides) -> RollingConstraints:
    base = dict(
        delta_w=75.0, delta_t=0.75, delta_h=7.0, delta_theta=45.0,
        kz=3_000_000.0, lr=3, m_min=60, m_max=100, soft_transition_limit=3,
    )
    base.update(overrides)
    return RollingConstraints(**base)


class TestActiveCourse:
    def test_no_active_course_returns_null(self, api_client, db_session):
        r = api_client.get("/api/courses/active")
        assert r.status_code == 200
        assert r.json() is None

    def test_active_course_reflects_v_active_course_state_view(self, api_client, db_session):
        from app.db.models import SlabOrder

        course = crud.start_new_course(db_session, constraints=_constraints())
        order = SlabOrder(
            steel_grade="X", width_mm=1000, thickness_mm=2, hardness=40, heating_temp_c=850,
            slab_width_mm=1000, slab_thickness_mm=200, slab_length_mm=8000,
            theoretical_rolling_length=123.456, order_class="main", status="scheduled", source="synthetic",
        )
        db_session.add(order)
        db_session.flush()
        crud.append_course_slot(
            db_session, course=course, slab_order=order, role="main",
            cumulative_length_mm=123.456, reverse_width_events_count=0, is_reverse_width=False,
        )

        r = api_client.get("/api/courses/active")
        assert r.status_code == 200
        body = r.json()
        assert body["course_id"] == course.id
        assert body["order_count"] == 1
        assert len(body["slots"]) == 1
        assert body["slots"][0]["slab_order_id"] == order.id
        assert body["slots"][0]["role"] == "main"


class TestListCourses:
    def test_lists_courses_ordered_desc_and_filters_by_status(self, api_client, db_session):
        c1 = crud.start_new_course(db_session, constraints=_constraints())
        crud.complete_course(db_session, c1, m_min=1)
        c2 = crud.start_new_course(db_session, constraints=_constraints())

        r = api_client.get("/api/courses")
        assert r.status_code == 200
        ids = [row["id"] for row in r.json()]
        assert ids.index(c2.id) < ids.index(c1.id)  # course_number DESC

        r2 = api_client.get("/api/courses", params={"status": "active"})
        statuses = {row["status"] for row in r2.json()}
        assert statuses <= {"active"}


class TestCourseDetail:
    def test_returns_404_for_unknown_course(self, api_client, db_session):
        r = api_client.get("/api/courses/999999999")
        assert r.status_code == 404

    def test_returns_course_with_slots(self, api_client, db_session):
        from app.db.models import SlabOrder

        course = crud.start_new_course(db_session, constraints=_constraints())
        order = SlabOrder(
            steel_grade="X", width_mm=1000, thickness_mm=2, hardness=40, heating_temp_c=850,
            slab_width_mm=1000, slab_thickness_mm=200, slab_length_mm=8000,
            theoretical_rolling_length=50.0, order_class="main", status="scheduled", source="synthetic",
        )
        db_session.add(order)
        db_session.flush()
        crud.append_course_slot(
            db_session, course=course, slab_order=order, role="main",
            cumulative_length_mm=50.0, reverse_width_events_count=0, is_reverse_width=False,
        )

        r = api_client.get(f"/api/courses/{course.id}")
        assert r.status_code == 200
        body = r.json()
        assert body["id"] == course.id
        assert len(body["slots"]) == 1
        assert body["slots"][0]["cumulative_length_mm"] == 50.0
