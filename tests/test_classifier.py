from the_vision.classifier import classify
from the_vision.config import RuleConfig
from the_vision.types import Status

from .helpers import SEATS, SW, frames, person, phone_near, seat_center

RULES = RuleConfig()


def status_of(tick, name):
    return next(s for s in tick.seats if s.name == name).status


def at(name, **kw):
    x, y = seat_center(name)
    return person(x, y, **kw)


def test_empty_classroom_all_absent():
    tick = classify(frames([]), SEATS, RULES)
    assert all(s.status == Status.ABSENT for s in tick.seats)
    assert tick.alerts == []


def test_focused_reading():
    tick = classify(frames([at("S00", head=0.5)]), SEATS, RULES)
    assert status_of(tick, "S00") == Status.FOCUSED
    assert status_of(tick, "S01") == Status.ABSENT


def test_phone_in_hand():
    p = at("S01", head=0.4)
    tick = classify(frames([p], objects=[phone_near(p)]), SEATS, RULES)
    assert status_of(tick, "S01") == Status.PHONE


def test_phone_left_on_desk_corner_is_ignored():
    p = at("S01", head=0.4)
    x, y, _ = p.keypoints[9]
    far = phone_near(p)
    far.bbox = (x + 2.5 * SW, y - 10, x + 2.5 * SW + 12, y + 10)
    tick = classify(frames([p], objects=[far]), SEATS, RULES)
    assert status_of(tick, "S01") == Status.FOCUSED


def test_phone_on_neighbours_seat_not_attributed():
    p0, p1 = at("S00"), at("S01")
    tick = classify(frames([p0, p1], objects=[phone_near(p1)]), SEATS, RULES)
    assert status_of(tick, "S00") == Status.FOCUSED
    assert status_of(tick, "S01") == Status.PHONE


def test_sleeping_head_on_desk():
    tick = classify(frames([at("S02", head=-0.1)]), SEATS, RULES)
    assert status_of(tick, "S02") == Status.SLEEPING


def test_face_hidden_with_shoulders_visible_is_sleeping():
    tick = classify(frames([at("S02", face=False)]), SEATS, RULES)
    assert status_of(tick, "S02") == Status.SLEEPING


def test_turned_head_is_distracted():
    tick = classify(frames([at("S10", head=0.8, turn=0.7)]), SEATS, RULES)
    r = next(s for s in tick.seats if s.name == "S10")
    assert r.status == Status.DISTRACTED
    assert "右" in r.reason


def test_brief_glance_is_not_distracted():
    seq = [[at("S10", turn=0.7)], [at("S10")], [at("S10")], [at("S10")], [at("S10")]]
    tick = classify(frames(*seq), SEATS, RULES)
    assert status_of(tick, "S10") == Status.FOCUSED


def test_large_motion_is_active():
    seq = [[at("S11", dx=d, wrists_up=True)] for d in (0, 30, -10, 30, 0)]
    tick = classify(frames(*seq), SEATS, RULES)
    assert status_of(tick, "S11") == Status.ACTIVE


def test_student_missing_in_most_frames_is_absent():
    seq = [[at("S12")], [], [], [], []]
    tick = classify(frames(*seq), SEATS, RULES)
    assert status_of(tick, "S12") == Status.ABSENT


def test_person_in_aisle_raises_wandering():
    walker = person(700, 300)  # 不在任何座位內
    tick = classify(frames([at("S00"), walker]), SEATS, RULES)
    kinds = [a.kind for a in tick.alerts]
    assert kinds == ["wandering"]


def test_teacher_in_ignore_zone_no_alert():
    teacher = person(700, 300)
    tick = classify(frames([teacher]), SEATS, RULES, ignore_zones=[(600, 150, 800, 450)])
    assert tick.alerts == []


def test_fall_detected():
    tick = classify(frames([person(700, 500, lying=True)]), SEATS, RULES)
    assert "fall" in [a.kind for a in tick.alerts]
    assert any(a.level == "danger" for a in tick.alerts)


def test_two_people_wrestling_in_aisle():
    seq = []
    for d in (0, 25, -15, 25, 0):
        seq.append([person(700, 300, dx=d, wrists_up=True), person(745, 300, dx=-d, wrists_up=True)])
    tick = classify(frames(*seq), SEATS, RULES)
    assert "fighting" in [a.kind for a in tick.alerts]


def test_neighbours_both_active_raise_alert():
    seq = []
    for d in (0, 30, -10, 30, 0):
        seq.append([at("S00", dx=d, wrists_up=True), at("S01", dx=-d, wrists_up=True)])
    tick = classify(frames(*seq), SEATS, RULES)
    assert status_of(tick, "S00") == Status.ACTIVE
    assert status_of(tick, "S01") == Status.ACTIVE
    fights = [a for a in tick.alerts if a.kind == "fighting"]
    assert len(fights) == 1
    assert "S00" in fights[0].message and "S01" in fights[0].message


def test_far_apart_active_seats_no_fight_alert():
    seq = []
    for d in (0, 30, -10, 30, 0):
        seq.append([at("S00", dx=d, wrists_up=True), at("S12", dx=-d, wrists_up=True)])
    tick = classify(frames(*seq), SEATS, RULES)
    assert [a for a in tick.alerts if a.kind == "fighting"] == []


def test_one_person_per_seat():
    # 兩人都站在 S00 範圍內：一人分配給 S00，另一人不會被算到隔壁座位
    x, y = seat_center("S00")
    tick = classify(frames([person(x - 10, y), person(x + 30, y)]), SEATS, RULES)
    assert status_of(tick, "S00") == Status.FOCUSED
    assert status_of(tick, "S01") == Status.ABSENT
