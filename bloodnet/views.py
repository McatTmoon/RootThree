import csv
import hashlib
import hmac
import json
import math
import os
import threading
import uuid
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET

from .models import BloodRequest, IdempotencyRecord
from .inventory import allocate_inventory_for_request, fetch_sim_time, process_stock_arrivals
from .donors import send_donor_invitations, stop_donor_outreach

IDEMPOTENCY_LOCK = threading.Lock()

GROUPS = {"O+", "A+", "B+", "AB+", "O-", "A-", "B-", "AB-"}
PRODUCTS = {"red_cells", "platelets", "plasma"}
URGENCY = {"critical", "urgent", "planned"}
ALLOWED_REQUEST_FIELDS = {"hospital_id", "blood_group", "product", "units", "urgency", "note"}
REQUIRED_REQUEST_FIELDS = {"hospital_id", "blood_group", "product", "units", "urgency"}

_REGISTERED_HOSPITALS = None


def get_registered_hospitals():
    global _REGISTERED_HOSPITALS
    if _REGISTERED_HOSPITALS is None:
        csv_path = settings.BASE_DIR / "participant_kit" / "hospitals.csv"
        if csv_path.exists():
            with open(csv_path, newline="", encoding="utf-8") as f:
                _REGISTERED_HOSPITALS = {row["hospital_id"] for row in csv.DictReader(f) if "hospital_id" in row}
        else:
            _REGISTERED_HOSPITALS = set()
    return _REGISTERED_HOSPITALS


def is_suspicious_request(hospital_id, units, urgency, sim_time):
    """
    Detect suspicious / abusive over-demand bursts to hold in 'pending_review'
    until verified by a coordinator via POST /requests/{id}/approve:
    1. Oversized critical demand spike (units >= 7 with critical urgency).
    2. Rapid-fire burst from the same hospital (>= 2 requests within 15 sim-minutes).
    """
    if units >= 7 and urgency == "critical":
        return True
    if sim_time > 0:
        recent_count = BloodRequest.objects.filter(
            hospital_id=hospital_id,
            created_sim_min__gte=sim_time - 15.0,
            created_sim_min__lte=sim_time + 1.0,
        ).count()
        if recent_count >= 2:
            return True
    return False


def is_authenticated_hospital(request):
    expected_token = os.environ.get("HOSPITAL_TOKEN", "hospital-token")
    auth_header = request.headers.get("Authorization", "")
    return hmac.compare_digest(auth_header.encode("utf-8"), f"Bearer {expected_token}".encode("utf-8"))


@require_GET
def health(request):
    """GET /health - Service health check defined in the BloodNet OpenAPI contract."""
    return JsonResponse({"ok": True}, status=200)


@csrf_exempt
def requests_collection(request):
    """POST /requests - Create official BloodNet request with idempotency support."""
    if request.method != "POST":
        return JsonResponse(
            {"error": {"code": "method_not_allowed", "message": f"Method {request.method} not allowed"}},
            status=405,
        )

    # 1. Authentication
    if not is_authenticated_hospital(request):
        return JsonResponse(
            {"error": {"code": "unauthorized", "message": "Missing or invalid hospital token"}},
            status=401,
        )

    # 2. Idempotency-Key header validation
    key = request.headers.get("Idempotency-Key")
    if not key or len(key.strip()) == 0 or len(key) > 128:
        return JsonResponse(
            {"error": {"code": "missing_idempotency_key", "message": "Idempotency-Key required (1-128 characters)"}},
            status=400,
        )

    # 3. Parse JSON body
    try:
        raw_body = request.body.decode("utf-8") if request.body else "{}"
        body = json.loads(raw_body)
    except Exception:
        return JsonResponse(
            {"error": {"code": "validation_error", "message": "Invalid JSON body"}},
            status=400,
        )

    if not isinstance(body, dict):
        return JsonResponse(
            {"error": {"code": "validation_error", "message": "Request body must be a JSON object"}},
            status=400,
        )

    body_hash_val = hashlib.sha256(json.dumps(body, sort_keys=True).encode("utf-8")).hexdigest()

    # 4. Check existing idempotency record or create new request atomically
    with IDEMPOTENCY_LOCK:
        with transaction.atomic():
            existing = IdempotencyRecord.objects.select_for_update().filter(key=key).first()
            if existing:
                if existing.body_hash == body_hash_val:
                    # Idempotent replay: 200 with stored response
                    return JsonResponse(existing.response_body, status=200)
                else:
                    # Key reused with different body: 422
                    return JsonResponse(
                        {"error": {"code": "idempotency_key_reuse", "message": "same key, different body"}},
                        status=422,
                    )

            # 5. Schema and field validation
            extra_fields = set(body.keys()) - ALLOWED_REQUEST_FIELDS
            if extra_fields:
                return JsonResponse(
                    {"error": {"code": "validation_error", "message": f"Unexpected fields: {list(extra_fields)}"}},
                    status=400,
                )

            missing_fields = REQUIRED_REQUEST_FIELDS - set(body.keys())
            if missing_fields:
                return JsonResponse(
                    {"error": {"code": "validation_error", "message": f"Missing required fields: {list(missing_fields)}"}},
                    status=400,
                )

            hospital_id = body.get("hospital_id")
            if hospital_id not in get_registered_hospitals():
                return JsonResponse(
                    {"error": {"code": "unknown_hospital", "message": f"Unregistered hospital_id '{hospital_id}'"}},
                    status=404,
                )

            blood_group = body.get("blood_group")
            if blood_group not in GROUPS:
                return JsonResponse(
                    {"error": {"code": "validation_error", "message": f"Invalid blood_group '{blood_group}'"}},
                    status=400,
                )

            product = body.get("product")
            if product not in PRODUCTS:
                return JsonResponse(
                    {"error": {"code": "validation_error", "message": f"Invalid product '{product}'"}},
                    status=400,
                )

            urgency = body.get("urgency")
            if urgency not in URGENCY:
                return JsonResponse(
                    {"error": {"code": "validation_error", "message": f"Invalid urgency '{urgency}'"}},
                    status=400,
                )

            units = body.get("units")
            if isinstance(units, bool) or not isinstance(units, int) or units < 1 or units > 20:
                return JsonResponse(
                    {"error": {"code": "validation_error", "message": "units must be integer between 1 and 20"}},
                    status=400,
                )

            note = body.get("note", "")
            if not isinstance(note, str) or len(note) > 500:
                return JsonResponse(
                    {"error": {"code": "validation_error", "message": "note must be a string up to 500 chars"}},
                    status=400,
                )

            # Parse simulation time header
            sim_time_hdr = request.headers.get("X-Sim-Time")
            sim_time = 0.0
            if sim_time_hdr:
                try:
                    parsed_sim = float(sim_time_hdr)
                    if math.isfinite(parsed_sim) and parsed_sim >= 0.0:
                        sim_time = parsed_sim
                except (ValueError, TypeError):
                    pass

            # 6. Create BloodRequest record (with suspicious/abuse burst check)
            initial_status = (
                "pending_review"
                if is_suspicious_request(hospital_id, units, urgency, sim_time)
                else "open"
            )
            rid = "R-" + uuid.uuid4().hex[:12]
            blood_req = BloodRequest.objects.create(
                request_id=rid,
                hospital_id=hospital_id,
                blood_group=blood_group,
                product=product,
                urgency=urgency,
                needed=units,
                note=note,
                status=initial_status,
                confirmed=0,
                en_route=0,
                arrived=0,
                fulfilled=0,
                stock_inflight=0,
                created_sim_min=sim_time,
            )

            # 7. Record idempotency entry
            response_payload = {
                "request_id": blood_req.request_id,
                "status": blood_req.status,
                "needed": blood_req.needed,
            }

            IdempotencyRecord.objects.create(
                key=key,
                body_hash=body_hash_val,
                response_code=201,
                response_body=response_payload,
                request=blood_req,
            )

    # Trigger inventory allocation outside DB transaction (only if approved/open)
    if blood_req.status in ("open", "mobilizing"):
        allocate_inventory_for_request(blood_req.request_id)
        blood_req.refresh_from_db()
        if blood_req.shortage > 0 and blood_req.status in ("open", "mobilizing"):
            send_donor_invitations(blood_req.request_id)

    return JsonResponse(response_payload, status=201)


@csrf_exempt
def request_approve(request, request_id):
    """POST /requests/{id}/approve - Approve pending review request."""
    if request.method != "POST":
        return JsonResponse(
            {"error": {"code": "method_not_allowed", "message": f"Method {request.method} not allowed"}},
            status=405,
        )

    expected_token = os.environ.get("COORDINATOR_TOKEN", "coordinator-token")
    auth_header = request.headers.get("Authorization", "")
    if not hmac.compare_digest(auth_header.encode("utf-8"), f"Bearer {expected_token}".encode("utf-8")):
        return JsonResponse(
            {"error": {"code": "unauthorized", "message": "Coordinator token required"}},
            status=401,
        )

    with IDEMPOTENCY_LOCK:
        with transaction.atomic():
            blood_req = BloodRequest.objects.select_for_update().filter(request_id=request_id).first()
            if not blood_req:
                return JsonResponse(
                    {"error": {"code": "not_found", "message": f"Request '{request_id}' not found"}},
                    status=404,
                )

            if blood_req.status != "pending_review":
                return JsonResponse(
                    {"error": {"code": "not_pending_review", "message": f"Request is not pending review ({blood_req.status})"}},
                    status=409,
                )

            blood_req.status = "open"
            blood_req.save()

    allocate_inventory_for_request(blood_req.request_id)
    blood_req.refresh_from_db()
    if blood_req.shortage > 0 and blood_req.status in ("open", "mobilizing"):
        send_donor_invitations(blood_req.request_id)
    blood_req.refresh_from_db()

    return JsonResponse(
        {"request_id": blood_req.request_id, "status": blood_req.status},
        status=200,
    )


@csrf_exempt
def request_cancel(request, request_id):
    """POST /requests/{id}/cancel - Cancel an active request."""
    if request.method != "POST":
        return JsonResponse(
            {"error": {"code": "method_not_allowed", "message": f"Method {request.method} not allowed"}},
            status=405,
        )

    if not is_authenticated_hospital(request):
        return JsonResponse(
            {"error": {"code": "unauthorized", "message": "Missing or invalid hospital token"}},
            status=401,
        )

    with IDEMPOTENCY_LOCK:
        with transaction.atomic():
            blood_req = BloodRequest.objects.select_for_update().filter(request_id=request_id).first()
            if not blood_req:
                return JsonResponse(
                    {"error": {"code": "not_found", "message": f"Request '{request_id}' not found"}},
                    status=404,
                )

            if blood_req.status not in ("cancelled", "fulfilled"):
                blood_req.status = "cancelled"
                blood_req.save()

    stop_donor_outreach(blood_req, template="cancelled")

    return JsonResponse(
        {"request_id": blood_req.request_id, "status": blood_req.status},
        status=200,
    )


@csrf_exempt
def request_amend(request, request_id):
    """POST /requests/{id}/amend - Amend urgency of an active request."""
    if request.method != "POST":
        return JsonResponse(
            {"error": {"code": "method_not_allowed", "message": f"Method {request.method} not allowed"}},
            status=405,
        )

    if not is_authenticated_hospital(request):
        return JsonResponse(
            {"error": {"code": "unauthorized", "message": "Missing or invalid hospital token"}},
            status=401,
        )

    try:
        b = json.loads(request.body.decode("utf-8") if request.body else "{}")
    except Exception:
        return JsonResponse({"error": {"code": "validation_error", "message": "bad json"}}, status=400)

    if not isinstance(b, dict) or set(b.keys()) != {"urgency"}:
        return JsonResponse({"error": {"code": "validation_error", "message": "only urgency field allowed"}}, status=400)

    urg = b.get("urgency")
    if urg not in URGENCY:
        return JsonResponse({"error": {"code": "validation_error", "message": "urgency"}}, status=400)

    with IDEMPOTENCY_LOCK:
        with transaction.atomic():
            blood_req = BloodRequest.objects.select_for_update().filter(request_id=request_id).first()
            if not blood_req:
                return JsonResponse(
                    {"error": {"code": "not_found", "message": f"Request '{request_id}' not found"}},
                    status=404,
                )

            if blood_req.status in ("cancelled", "fulfilled", "expired"):
                return JsonResponse(
                    {"error": {"code": "not_amendable", "message": blood_req.status}},
                    status=409,
                )

            blood_req.urgency = urg
            blood_req.save()

    if blood_req.status in ("open", "mobilizing") and blood_req.shortage > 0:
        send_donor_invitations(blood_req.request_id)

    return JsonResponse(
        {"request_id": blood_req.request_id, "urgency": urg},
        status=200,
    )


@csrf_exempt
def request_detail(request, request_id):
    """GET /requests/{id} - Retrieve current request counters and state."""
    # 1. Authentication
    if not is_authenticated_hospital(request):
        return JsonResponse(
            {"error": {"code": "unauthorized", "message": "Missing or invalid hospital token"}},
            status=401,
        )

    if request.method == "GET":
        blood_req = BloodRequest.objects.filter(request_id=request_id).first()
        if blood_req is None:
            return JsonResponse(
                {"error": {"code": "not_found", "message": f"Request '{request_id}' not found"}},
                status=404,
            )

        sim_now = fetch_sim_time(fallback=blood_req.created_sim_min)
        process_stock_arrivals(sim_now)
        blood_req.refresh_from_db()

        data = {
            "request_id": blood_req.request_id,
            "status": blood_req.status,
            "needed": blood_req.needed,
            "confirmed": blood_req.confirmed,
            "en_route": blood_req.en_route,
            "arrived": blood_req.arrived,
            "fulfilled": blood_req.fulfilled,
            "hospital_id": blood_req.hospital_id,
            "blood_group": blood_req.blood_group,
            "product": blood_req.product,
            "urgency": blood_req.urgency,
            "stock_inflight": blood_req.stock_inflight,
            "shortage": blood_req.shortage,
            "created_sim_min": round(blood_req.created_sim_min, 2),
        }
        if blood_req.note:
            data["note"] = blood_req.note

        return JsonResponse(data, status=200)

    return JsonResponse(
        {"error": {"code": "method_not_allowed", "message": f"Method {request.method} not allowed"}},
        status=405,
    )
