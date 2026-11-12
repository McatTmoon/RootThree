import csv
from datetime import datetime
import json
import logging
import os
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from django.conf import settings
from django.db import transaction

from .compat import is_compatible
from .inventory import fetch_sim_time, get_gateway_url
from .models import BloodRequest, DonorInvitation, DonorTrack

logger = logging.getLogger(__name__)

SNAPSHOT = datetime(2027, 1, 15, 0, 0, 0)
DON_TYPE = {"red_cells": 1, "platelets": 2, "plasma": 3}
INTERVAL = {"red_cells": {"M": 60, "F": 90}, "platelets": 14, "plasma": 14}
CROSS_BLOCK = 14

_DONORS_CACHE = None
_DEFER_CACHE = None
_TRAVEL_CACHE = None
_AREA_CENTER_CACHE = None
_CENTER_HOSP_CACHE = None
_CENTERS_META = None
_RELIABILITY_CACHE = None


def get_self_url():
    port = os.environ.get("PORT", "8000")
    return os.environ.get("SELF_URL", f"http://localhost:{port}").rstrip("/")


def load_donor_data():
    global _DONORS_CACHE, _DEFER_CACHE, _TRAVEL_CACHE, _AREA_CENTER_CACHE, _CENTER_HOSP_CACHE, _CENTERS_META, _RELIABILITY_CACHE
    if _DONORS_CACHE is None:
        kit_dir = settings.BASE_DIR / "participant_kit"

        # 1. Load donors.csv
        donors_path = kit_dir / "donors.csv"
        if donors_path.exists():
            with open(donors_path, newline="", encoding="utf-8") as f:
                _DONORS_CACHE = list(csv.DictReader(f))
        else:
            _DONORS_CACHE = []

        # 2. Load donor_events.csv (temporary deferrals)
        _DEFER_CACHE = {}
        events_path = kit_dir / "donor_events.csv"
        if events_path.exists():
            with open(events_path, newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    did = row.get("donor_id")
                    defer_until = row.get("defer_until")
                    if did and defer_until:
                        try:
                            dt = datetime.fromisoformat(defer_until)
                            _DEFER_CACHE[did] = max(_DEFER_CACHE.get(did, datetime.min), dt)
                        except ValueError:
                            pass

        # 3. Load travel_area_to_hospital.csv
        _TRAVEL_CACHE = {}
        travel_path = kit_dir / "travel_area_to_hospital.csv"
        if travel_path.exists():
            with open(travel_path, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                hosp_cols = [c for c in reader.fieldnames if c != "area_id"]
                for row in reader:
                    aid = row["area_id"]
                    for h in hosp_cols:
                        try:
                            _TRAVEL_CACHE[(aid, h)] = float(row[h])
                        except (ValueError, TypeError):
                            pass

        # 4. Load centers.csv, travel_area_to_center.csv, and travel_center_to_hospital.csv
        _CENTERS_META = {}
        centers_path = kit_dir / "centers.csv"
        if centers_path.exists():
            with open(centers_path, newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    cid = row["center_id"]
                    _CENTERS_META[cid] = {
                        "open_hour": int(row.get("open_hour", 0)),
                        "close_hour": int(row.get("close_hour", 24)),
                        "beds": int(row.get("beds", 5)),
                    }

        _AREA_CENTER_CACHE = {}
        ac_path = kit_dir / "travel_area_to_center.csv"
        if ac_path.exists():
            with open(ac_path, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                center_cols = [c for c in reader.fieldnames if c != "area_id"]
                for row in reader:
                    aid = row["area_id"]
                    best_c, best_t = None, 999.0
                    for c in center_cols:
                        try:
                            t_val = float(row[c])
                            if t_val < best_t:
                                best_t = t_val
                                best_c = c
                        except (ValueError, TypeError):
                            pass
                    if best_c:
                        _AREA_CENTER_CACHE[aid] = (best_c, best_t)

        _CENTER_HOSP_CACHE = {}
        ch_path = kit_dir / "travel_center_to_hospital.csv"
        if ch_path.exists():
            with open(ch_path, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                hosp_cols = [c for c in reader.fieldnames if c != "center_id"]
                for row in reader:
                    cid = row["center_id"]
                    for h in hosp_cols:
                        try:
                            _CENTER_HOSP_CACHE[(cid, h)] = float(row[h])
                        except (ValueError, TypeError):
                            pass

        # 5. Load empirical donor reliability from history/responses.csv (offline ML/bayesian prior)
        _RELIABILITY_CACHE = {}
        resp_path = kit_dir / "history" / "responses.csv"
        if resp_path.exists():
            try:
                import pandas as pd
                df = pd.read_csv(resp_path, usecols=["donor_id", "accepted", "donated"])
                grp = df.groupby("donor_id").agg(
                    n=("accepted", "count"),
                    acc=("accepted", "sum"),
                    don=("donated", "sum"),
                )
                # Bayesian smoothed probability: (don + 0.5*acc + 1.0) / (n + 3.0)
                scores = (grp["don"] + 0.5 * grp["acc"] + 1.0) / (grp["n"] + 3.0)
                _RELIABILITY_CACHE = scores.to_dict()
            except Exception as exc:
                logger.debug("Could not compute empirical reliability: %s", exc)


def days_since_snapshot(dt):
    return (dt - SNAPSHOT).total_seconds() / 86400.0


def is_donor_eligible(donor, product, sim_time_min):
    """
    Check donor eligibility based on published rules:
    - Permanent exclusion
    - Age (18-65) & Weight (>= 50 kg)
    - Temporary deferral from donor_events.csv
    - Donation intervals and cross-product block
    """
    load_donor_data()

    if donor.get("permanently_excluded") in ("1", 1, True, "true"):
        return False

    did = donor.get("donor_id")
    if did in _DEFER_CACHE:
        sim_days = sim_time_min / 1440.0
        defer_days = days_since_snapshot(_DEFER_CACHE[did])
        if sim_days < defer_days:
            return False

    try:
        age = int(donor.get("age", 0))
        if not (18 <= age <= 65):
            return False
    except (ValueError, TypeError):
        return False

    try:
        weight = float(donor.get("weight_kg", 0.0))
        if weight < 50.0:
            return False
    except (ValueError, TypeError):
        return False

    last_at = donor.get("last_donation_at")
    last_typ = donor.get("last_donation_type")
    if not last_at:
        return True

    try:
        last_dt = datetime.fromisoformat(last_at)
        since_days = (sim_time_min / 1440.0) - days_since_snapshot(last_dt)
    except Exception:
        return True

    target_type = DON_TYPE.get(product, 1)
    if not last_typ:
        return True

    type_name_map = {1: "whole_blood", 2: "platelets", 3: "plasma"}
    expected_type_name = type_name_map.get(target_type)

    if last_typ == expected_type_name:
        if product == "red_cells":
            sex = donor.get("sex", "M")
            needed_interval = INTERVAL["red_cells"].get(sex, 60)
        else:
            needed_interval = INTERVAL.get(product, 14)
    else:
        needed_interval = CROSS_BLOCK

    return since_days >= needed_interval


def post_gateway_message(payload, gateway_url=None, max_retries=2):
    """
    Post a message to Gateway /messages with bounded retries on 429 and 503.
    Network connection errors fail fast.
    """
    base_url = (gateway_url or get_gateway_url()).rstrip("/")
    url = f"{base_url}/messages"
    body_bytes = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body_bytes,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    for attempt in range(max_retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return resp.status, data
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                data = json.loads(raw.decode("utf-8"))
            except Exception:
                data = {"raw": raw.decode("utf-8", errors="replace")}
            if e.code in (429, 503) and attempt < max_retries:
                retry_after = e.headers.get("Retry-After", "0.2")
                try:
                    wait = float(retry_after)
                except ValueError:
                    wait = 0.2
                time.sleep(min(max(wait, 0.1), 1.0))
                continue
            return e.code, data
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            # Network connection error (e.g. gateway not running) fails fast
            return 503, {"error": {"code": "gateway_unavailable", "message": str(e)}}

    return 500, {"error": {"code": "unknown_error", "message": "Failed after retries"}}


SLA_LIMITS = {"critical": 90.0, "urgent": 240.0, "planned": 1440.0}
VISIT_MIN = {"red_cells": 20.0, "platelets": 90.0, "plasma": 45.0}
PROC_MIN = 20.0


def is_in_quiet_hours(donor, sim_time_min):
    """Check if simulation clock is currently within the donor's local quiet hours."""
    try:
        qs = int(donor.get("quiet_start_hour", -1))
        qe = int(donor.get("quiet_end_hour", -1))
    except (ValueError, TypeError):
        return False
    if qs < 0 or qe < 0 or qs == qe:
        return False
    hour = int((sim_time_min % 1440.0) // 60.0)
    if qs > qe:
        return hour >= qs or hour < qe
    return qs <= hour < qe


def score_donor_candidate(donor, blood_req, sim_time_min):
    """
    Offline Intelligent Donor Scoring (Expected Timely Yield):
    Combines historical empirical reliability (Bayes-smoothed from responses.csv),
    quiet-hour awareness, notification fatigue (notified_90d), screening pass traits,
    center opening-hour wait times, and end-to-end supply ETA against request SLA.
    Returns a priority tuple (lower is better for sorting).
    """
    load_donor_data()
    did = donor["donor_id"]
    aid = donor.get("area_id")
    hosp_id = blood_req.hospital_id
    product = blood_req.product
    sla = SLA_LIMITS.get(blood_req.urgency, 240.0)

    # 1. Estimate travel to nearest blood center + center opening wait + center->hospital
    c_info = (_AREA_CENTER_CACHE or {}).get(aid)
    if c_info:
        cid, t_ac = c_info
        t_ch = (_CENTER_HOSP_CACHE or {}).get((cid, hosp_id), 60.0)
        c_meta = (_CENTERS_META or {}).get(cid, {"open_hour": 0, "close_hour": 24})
        o_h, c_h = c_meta["open_hour"], c_meta["close_hour"]
        arr_min = sim_time_min + 7.0 + t_ac
        wait_open = 0.0
        if not (o_h == 0 and c_h == 24):
            tod = arr_min % 1440.0
            v_min = VISIT_MIN.get(product, 20.0)
            if tod < o_h * 60.0:
                wait_open = (o_h * 60.0) - tod
            elif tod + v_min > c_h * 60.0:
                wait_open = (1440.0 - tod) + (o_h * 60.0)
        total_eta = 7.0 + t_ac + wait_open + VISIT_MIN.get(product, 20.0) + PROC_MIN + t_ch
    else:
        t_ac = (_TRAVEL_CACHE or {}).get((aid, hosp_id), 999.0)
        total_eta = t_ac + 40.0

    # 2. Empirical reliability prior from history/responses.csv
    rel = (_RELIABILITY_CACHE or {}).get(did, 0.35)

    # 3. Quiet hours & fatigue penalties
    quiet_penalty = 1.0 if is_in_quiet_hours(donor, sim_time_min) else 0.0
    try:
        fatigue = float(donor.get("notified_90d", 0))
    except (ValueError, TypeError):
        fatigue = 0.0

    # 4. SLA feasibility (does expected supply arrive before SLA deadline?)
    sla_miss_penalty = 0 if total_eta <= sla else 1

    # Composite cost (lower is better): prioritize SLA-feasible, awake, high-reliability, nearby donors
    cost = (
        sla_miss_penalty * 500.0
        + quiet_penalty * 60.0
        + total_eta * 1.0
        - rel * 80.0
        + fatigue * 6.0
    )
    return round(cost, 3)


def send_donor_invitations(request_id, gateway_url=None, self_url=None, max_cap=None):
    """
    Send outreach wave to eligible, highest-scoring compatible donors for unresolved shortage.
    Follows approval rules (only active/open/mobilizing requests with shortage).
    Persists DonorInvitation and DonorTrack records.
    """
    load_donor_data()

    blood_req = BloodRequest.objects.filter(request_id=request_id).first()
    if not blood_req:
        return []

    # Approval check
    if blood_req.status in ("pending_review", "cancelled", "fulfilled", "expired"):
        return []

    shortage = blood_req.shortage
    if shortage <= 0:
        return []

    sim_time = fetch_sim_time(fallback=blood_req.created_sim_min)
    cb_url = self_url or get_self_url()

    # Find candidate donors
    already_invited = set(
        DonorTrack.objects.filter(request=blood_req).values_list("donor_id", flat=True)
    )
    # A2 rule + post-donation interval: exclude donors currently committed OR who already donated in this run
    busy_donors = set(
        DonorTrack.objects.filter(
            state__in=["accepted", "en_route", "arrived", "screen_pass", "donated"]
        ).exclude(request=blood_req).values_list("donor_id", flat=True)
    )

    candidates = []
    for d in _DONORS_CACHE:
        did = d["donor_id"]
        if did in already_invited or did in busy_donors:
            continue
        if not is_compatible(d["blood_group"], blood_req.blood_group, blood_req.product):
            continue
        if not is_donor_eligible(d, blood_req.product, sim_time):
            continue

        cost = score_donor_candidate(d, blood_req, sim_time)
        candidates.append((cost, d))

    # Sort by intelligent composite cost (lowest cost = highest expected timely yield)
    candidates.sort(key=lambda x: x[0])

    cap = max_cap or min(max(shortage * 6, 12), 48)
    selected = candidates[:cap]

    sent_invitations = []
    for travel_time, donor in selected:
        did = donor["donor_id"]
        nid = f"nt-{uuid.uuid4().hex}"

        # 1. Pre-persist invitation and track in DB
        with transaction.atomic():
            inv = DonorInvitation.objects.create(
                notification_id=nid,
                request=blood_req,
                donor_id=did,
                template="request_wave",
                status="queued",
                created_sim_min=sim_time,
            )
            track, _ = DonorTrack.objects.get_or_create(
                request=blood_req,
                donor_id=did,
                defaults={"state": "invited", "notification_id": nid},
            )

        payload = {
            "notification_id": nid,
            "donor_id": did,
            "template": "request_wave",
            "request_id": blood_req.request_id,
            "callback_url": cb_url,
        }

        code, resp = post_gateway_message(payload, gateway_url=gateway_url)
        with transaction.atomic():
            inv_locked = DonorInvitation.objects.select_for_update().get(id=inv.id)
            if code in (200, 202):
                inv_locked.status = "sent"
                inv_locked.save()
                sent_invitations.append({"notification_id": nid, "donor_id": did, "status": "sent"})
            elif code == 409:
                inv_locked.status = "sent"
                inv_locked.save()
            else:
                inv_locked.status = "failed"
                inv_locked.save()

        # If gateway is completely unreachable, fail fast and avoid repeating 24 times
        if code == 503 and resp.get("error", {}).get("code") == "gateway_unavailable":
            break

    return sent_invitations


def stop_donor_outreach(blood_req, template="not_needed", gateway_url=None, self_url=None):
    """
    Stop outreach for a request that has been cancelled, fulfilled, or expired.
    Notifies pending accepted donors with 'not_needed' or 'cancelled'.
    """
    cb_url = self_url or get_self_url()
    pending_tracks = DonorTrack.objects.filter(
        request=blood_req,
        state__in=["accepted", "invited"],
    )

    for track in pending_tracks:
        nid = f"nt-{uuid.uuid4().hex}"
        payload = {
            "notification_id": nid,
            "donor_id": track.donor_id,
            "template": template,
            "request_id": blood_req.request_id,
            "callback_url": cb_url,
        }
        post_gateway_message(payload, gateway_url=gateway_url)
        track.state = "stopped" if template == "not_needed" else "cancelled"
        track.save()
