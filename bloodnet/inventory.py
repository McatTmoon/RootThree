import json
import logging
import os
import time
import urllib.error
import urllib.request
import uuid

from django.conf import settings
from django.db import transaction

from .compat import is_compatible
from .models import BloodRequest, StockDispatch

logger = logging.getLogger(__name__)


def get_inventory_url():
    return os.environ.get("INVENTORY_URL", "http://localhost:9300").rstrip("/")


def get_gateway_url():
    return os.environ.get("GATEWAY_URL", "http://localhost:9100").rstrip("/")


def fetch_sim_time(fallback=0.0):
    """Fetch authoritative simulation clock from the Gateway if available."""
    gateway_url = get_gateway_url()
    try:
        req = urllib.request.Request(
            f"{gateway_url}/clock",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=1.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return float(data.get("sim_time", fallback))
    except Exception:
        return fallback


def fetch_live_inventory(inventory_url=None):
    """
    Fetch live center stock from the official Inventory service.
    Returns (sim_time, items_list).
    """
    base_url = (inventory_url or get_inventory_url()).rstrip("/")
    url = f"{base_url}/inventory"
    try:
        req = urllib.request.Request(
            url,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=1.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return float(data.get("sim_time", 0.0)), data.get("items", [])
    except Exception as exc:
        logger.debug("Failed to fetch live inventory from %s: %s", url, exc)
        return None, None


def dispatch_http_call(url, body, max_retries=2):
    """
    Perform dispatch POST call to Inventory service.
    Honors bounded retries for 429 (rate limit) and 503 (temporary failure) using the exact same body and dispatch_id.
    """
    payload_bytes = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload_bytes,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    for attempt in range(max_retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return resp.status, data
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                data = json.loads(raw.decode("utf-8"))
            except Exception:
                data = {"raw": raw.decode("utf-8", errors="replace")}
            if e.code in (429, 503) and attempt < max_retries:
                time.sleep(0.3)
                continue
            return e.code, data
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            if attempt < max_retries:
                time.sleep(0.3)
                continue
            return 503, {"error": {"code": "service_unavailable", "message": str(e)}}
    return 500, {"error": {"code": "unknown_error", "message": "Failed after retries"}}


def allocate_inventory_for_request(blood_request_id, inventory_url=None):
    """
    Attempt to cover remaining request need from center stock using FEFO and compatibility rules.
    Strictly follows approval rules (no dispatch for pending_review or terminal requests).
    Avoids holding SQLite write transactions open across network calls.
    """
    # 1. Inspect request state
    blood_req = BloodRequest.objects.filter(request_id=blood_request_id).first()
    if not blood_req:
        return []

    # Approval check: pending_review requests cannot receive inventory
    if blood_req.status in ("pending_review", "cancelled", "fulfilled", "expired"):
        return []

    needed = blood_req.needed
    fulfilled = blood_req.fulfilled
    inflight = blood_req.stock_inflight
    remaining = needed - fulfilled - inflight
    if remaining <= 0:
        return []

    # 2. Read live stock outside DB transaction
    sim_time, items = fetch_live_inventory(inventory_url)
    if items is None:
        return []

    if sim_time is None or sim_time == 0.0:
        sim_time = fetch_sim_time(fallback=blood_req.created_sim_min)

    # 3. Filter candidates: matching product, compatible blood group, unexpired
    candidates = []
    for it in items:
        if it.get("product") != blood_req.product:
            continue
        if not is_compatible(it.get("blood_group"), blood_req.blood_group, blood_req.product):
            continue
        exp = float(it.get("expires_sim_min", 0.0))
        if exp <= sim_time:
            continue
        units = int(it.get("units", 0))
        if units <= 0:
            continue
        candidates.append(it)

    # 4. FEFO sorting (First-Expiry-First-Out)
    candidates.sort(key=lambda x: (float(x.get("expires_sim_min", 1e18)), x.get("center_id", "")))

    # Plan picks up to remaining shortage
    picks = []
    to_cover = remaining
    for it in candidates:
        if to_cover <= 0:
            break
        take = min(int(it["units"]), to_cover)
        if take > 0:
            picks.append({
                "center_id": it["center_id"],
                "blood_group": it["blood_group"],
                "product": it["product"],
                "units": take,
            })
            to_cover -= take

    if not picks:
        return []

    # 5. Execute dispatches
    results = []
    base_url = (inventory_url or get_inventory_url()).rstrip("/")
    dispatch_url = f"{base_url}/inventory/dispatch"

    for pick in picks:
        # Re-verify remaining shortage
        blood_req.refresh_from_db()
        current_shortage = blood_req.needed - blood_req.fulfilled - blood_req.stock_inflight
        if current_shortage <= 0:
            break
        actual_units = min(pick["units"], current_shortage)
        if actual_units <= 0:
            break

        # A: Persist stable dispatch attempt in DB (committed immediately, no open write lock)
        dispatch_id = f"dsp-{blood_req.request_id[-8:]}-{uuid.uuid4().hex[:8]}"
        dispatch_record = StockDispatch.objects.create(
            dispatch_id=dispatch_id,
            request=blood_req,
            center_id=pick["center_id"],
            blood_group=pick["blood_group"],
            product=pick["product"],
            units=actual_units,
            hospital_id=blood_req.hospital_id,
            recipient_blood_group=blood_req.blood_group,
            status="pending",
        )

        body = {
            "dispatch_id": dispatch_id,
            "request_id": blood_req.request_id,
            "center_id": pick["center_id"],
            "blood_group": pick["blood_group"],
            "product": pick["product"],
            "units": actual_units,
            "hospital_id": blood_req.hospital_id,
            "recipient_blood_group": blood_req.blood_group,
        }

        # B: Execute network call outside any DB transaction
        code, resp_data = dispatch_http_call(dispatch_url, body)

        # C: Update dispatch and request counters in quick atomic transaction
        with transaction.atomic():
            req_locked = BloodRequest.objects.select_for_update().get(id=blood_req.id)
            disp_locked = StockDispatch.objects.select_for_update().get(id=dispatch_record.id)

            disp_locked.response_code = code
            if code in (200, 201):
                disp_locked.status = "dispatched"
                disp_locked.eta_sim_min = resp_data.get("eta_sim_min")
                disp_locked.save()

                req_locked.stock_inflight += actual_units
                if req_locked.fulfilled + req_locked.stock_inflight >= req_locked.needed:
                    if req_locked.status == "open":
                        req_locked.status = "mobilizing"
                req_locked.save()
                results.append({
                    "dispatch_id": dispatch_id,
                    "status": "dispatched",
                    "units": actual_units,
                    "eta_sim_min": resp_data.get("eta_sim_min"),
                })
            else:
                disp_locked.status = "failed"
                disp_locked.error_message = json.dumps(resp_data)
                disp_locked.save()
                results.append({
                    "dispatch_id": dispatch_id,
                    "status": "failed",
                    "code": code,
                    "error": resp_data,
                })

    return results


def retry_dispatch(dispatch_id, inventory_url=None):
    """
    Retry a pending or failed dispatch using its stable dispatch_id.
    Prevents double allocation because the Inventory service returns 200 with the original result.
    """
    disp = StockDispatch.objects.filter(dispatch_id=dispatch_id).first()
    if not disp:
        return False, "Dispatch not found"

    if disp.status == "dispatched":
        return True, "Already dispatched"

    base_url = (inventory_url or get_inventory_url()).rstrip("/")
    dispatch_url = f"{base_url}/inventory/dispatch"
    body = {
        "dispatch_id": disp.dispatch_id,
        "request_id": disp.request.request_id,
        "center_id": disp.center_id,
        "blood_group": disp.blood_group,
        "product": disp.product,
        "units": disp.units,
        "hospital_id": disp.hospital_id,
        "recipient_blood_group": disp.recipient_blood_group,
    }

    code, resp_data = dispatch_http_call(dispatch_url, body)

    with transaction.atomic():
        disp_locked = StockDispatch.objects.select_for_update().get(id=disp.id)
        req_locked = BloodRequest.objects.select_for_update().get(id=disp.request.id)

        disp_locked.response_code = code
        if code in (200, 201):
            if disp_locked.status != "dispatched":
                disp_locked.status = "dispatched"
                disp_locked.eta_sim_min = resp_data.get("eta_sim_min")
                disp_locked.save()

                req_locked.stock_inflight += disp.units
                if req_locked.fulfilled + req_locked.stock_inflight >= req_locked.needed:
                    if req_locked.status == "open":
                        req_locked.status = "mobilizing"
                req_locked.save()
            return True, resp_data
        else:
            disp_locked.status = "failed"
            disp_locked.error_message = json.dumps(resp_data)
            disp_locked.save()
            return False, resp_data


def process_stock_arrivals(sim_time):
    """
    Checks all in-flight stock dispatches whose arrival ETA has passed (eta_sim_min <= sim_time)
    and transitions them from stock_inflight to fulfilled.
    """
    if sim_time is None or sim_time <= 0:
        return 0

    count = 0
    newly_fulfilled = []
    with transaction.atomic():
        arrived_dispatches = StockDispatch.objects.select_for_update().filter(
            status="dispatched",
            eta_sim_min__isnull=False,
            eta_sim_min__lte=sim_time,
        )
        for disp in arrived_dispatches:
            disp.status = "delivered"
            disp.save()

            req = BloodRequest.objects.select_for_update().get(id=disp.request.id)
            req.stock_inflight = max(0, req.stock_inflight - disp.units)
            req.fulfilled += disp.units
            if req.fulfilled >= req.needed and req.status not in ("cancelled", "expired", "fulfilled"):
                req.status = "fulfilled"
                newly_fulfilled.append(req)
            elif req.fulfilled >= req.needed and req.status not in ("cancelled", "expired"):
                req.status = "fulfilled"
            req.save()
            count += 1

    if newly_fulfilled:
        from .donors import stop_donor_outreach
        for req in newly_fulfilled:
            stop_donor_outreach(req, template="not_needed")
    return count

