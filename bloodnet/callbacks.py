import json
import logging
import math
import uuid

from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .donors import get_self_url, post_gateway_message, send_donor_invitations, stop_donor_outreach
from .inventory import process_stock_arrivals
from .models import BloodRequest, CallbackEvent, DonorInvitation, DonorTrack
from .views import IDEMPOTENCY_LOCK

logger = logging.getLogger(__name__)

STATE_RANKS = {
    "invited": 1,
    "accepted": 2,
    "en_route": 3,
    "arrived": 4,
    "screen_pass": 5,
    "donated": 6,
}


def _parse_sim_time(val):
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        try:
            val = float(val)
        except (ValueError, TypeError):
            return None
    f = float(val)
    if not math.isfinite(f) or f < 0.0:
        return None
    return f


@csrf_exempt
def callback_gateway_status(request):
    """POST /callbacks/gateway-status - Gateway status callback for sent notifications."""
    if request.method != "POST":
        return JsonResponse({"error": {"code": "method_not_allowed", "message": "Method not allowed"}}, status=405)

    try:
        b = json.loads(request.body.decode("utf-8") if request.body else "{}")
    except Exception:
        return JsonResponse({"error": {"code": "validation_error", "message": "bad json"}}, status=400)

    if not isinstance(b, dict):
        return JsonResponse({"error": {"code": "validation_error", "message": "json object required"}}, status=400)

    for field in ("event_id", "notification_id", "request_id", "donor_id", "status", "sim_time"):
        if field not in b:
            return JsonResponse({"error": {"code": "validation_error", "message": f"missing {field}"}}, status=400)

    if b["status"] not in ("queued", "sent", "delivered", "failed", "expired"):
        return JsonResponse({"error": {"code": "validation_error", "message": "invalid status"}}, status=400)

    sim_time = _parse_sim_time(b["sim_time"])
    if sim_time is None:
        return JsonResponse({"error": {"code": "validation_error", "message": "invalid sim_time"}}, status=400)

    event_id = str(b["event_id"])

    with IDEMPOTENCY_LOCK:
        with transaction.atomic():
            # Deduplication by event_id
            if CallbackEvent.objects.select_for_update().filter(event_id=event_id).exists():
                return JsonResponse({"ok": True}, status=200)

            CallbackEvent.objects.create(
                event_id=event_id,
                event_type="gateway_status",
                request_id=str(b["request_id"]),
                donor_id=str(b["donor_id"]),
                payload=b,
            )

            inv = DonorInvitation.objects.select_for_update().filter(notification_id=str(b["notification_id"])).first()
            if inv:
                inv.status = b["status"]
                inv.save()

    process_stock_arrivals(sim_time)
    return JsonResponse({"ok": True}, status=200)


@csrf_exempt
def callback_donor_response(request):
    """POST /callbacks/donor-response - Donor reaction (accepted/declined) callback."""
    if request.method != "POST":
        return JsonResponse({"error": {"code": "method_not_allowed", "message": "Method not allowed"}}, status=405)

    try:
        b = json.loads(request.body.decode("utf-8") if request.body else "{}")
    except Exception:
        return JsonResponse({"error": {"code": "validation_error", "message": "bad json"}}, status=400)

    if not isinstance(b, dict):
        return JsonResponse({"error": {"code": "validation_error", "message": "json object required"}}, status=400)

    for field in ("event_id", "request_id", "donor_id", "notification_id", "response", "sim_time"):
        if field not in b:
            return JsonResponse({"error": {"code": "validation_error", "message": f"missing {field}"}}, status=400)

    if b["response"] not in ("accepted", "declined"):
        return JsonResponse({"error": {"code": "validation_error", "message": "invalid response"}}, status=400)

    sim_time = _parse_sim_time(b["sim_time"])
    if sim_time is None:
        return JsonResponse({"error": {"code": "validation_error", "message": "invalid sim_time"}}, status=400)

    event_id = str(b["event_id"])

    confirm_payload = None
    not_needed_payload = None

    with IDEMPOTENCY_LOCK:
        with transaction.atomic():
            # Deduplication by event_id
            if CallbackEvent.objects.select_for_update().filter(event_id=event_id).exists():
                return JsonResponse({"ok": True}, status=200)

            CallbackEvent.objects.create(
                event_id=event_id,
                event_type="donor_response",
                request_id=str(b["request_id"]),
                donor_id=str(b["donor_id"]),
                payload=b,
            )

            req = BloodRequest.objects.select_for_update().filter(request_id=str(b["request_id"])).first()
            if not req:
                return JsonResponse({"ok": True}, status=200)

            track, _ = DonorTrack.objects.select_for_update().get_or_create(
                request=req,
                donor_id=str(b["donor_id"]),
                defaults={"state": "invited"},
            )

            if b["response"] == "accepted":
                active_confirmed = DonorTrack.objects.filter(
                    request=req,
                    state__in=["accepted", "en_route", "arrived", "screen_pass"],
                ).exclude(id=track.id).count()
                max_needed_confirmations = max(req.shortage * 2, req.shortage + 2)

                if req.status in ("cancelled", "fulfilled", "expired") or req.shortage <= 0 or active_confirmed >= max_needed_confirmations:
                    track.state = "stopped"
                    track.save()
                    not_needed_payload = {
                        "notification_id": f"nt-{uuid.uuid4().hex}",
                        "donor_id": str(b["donor_id"]),
                        "template": "not_needed",
                        "request_id": req.request_id,
                        "callback_url": get_self_url(),
                    }
                else:
                    cur_rank = STATE_RANKS.get(track.state, 0)
                    if cur_rank < 2 and track.state not in ("declined", "cancelled", "no_show"):
                        track.state = "accepted"
                        track.accepted_sim_min = sim_time
                        track.save()
                        req.confirmed += 1
                        req.save()

                        confirm_payload = {
                            "notification_id": f"nt-{uuid.uuid4().hex}",
                            "donor_id": str(b["donor_id"]),
                            "template": "confirmed",
                            "request_id": req.request_id,
                            "callback_url": get_self_url(),
                        }
            elif b["response"] == "declined":
                if track.state == "invited":
                    track.state = "declined"
                    track.save()

    # Network calls outside DB transaction
    if confirm_payload:
        post_gateway_message(confirm_payload)
    if not_needed_payload:
        post_gateway_message(not_needed_payload)

    process_stock_arrivals(sim_time)
    return JsonResponse({"ok": True}, status=200)


@csrf_exempt
def callback_donor_progress(request):
    """POST /callbacks/donor-progress - Donor journey progress callback."""
    if request.method != "POST":
        return JsonResponse({"error": {"code": "method_not_allowed", "message": "Method not allowed"}}, status=405)

    try:
        b = json.loads(request.body.decode("utf-8") if request.body else "{}")
    except Exception:
        return JsonResponse({"error": {"code": "validation_error", "message": "bad json"}}, status=400)

    if not isinstance(b, dict):
        return JsonResponse({"error": {"code": "validation_error", "message": "json object required"}}, status=400)

    for field in ("event_id", "request_id", "donor_id", "event", "sim_time"):
        if field not in b:
            return JsonResponse({"error": {"code": "validation_error", "message": f"missing {field}"}}, status=400)

    if b["event"] not in ("en_route", "arrived", "screen_pass", "screen_fail", "donated", "no_show"):
        return JsonResponse({"error": {"code": "validation_error", "message": "invalid event"}}, status=400)

    sim_time = _parse_sim_time(b["sim_time"])
    if sim_time is None:
        return JsonResponse({"error": {"code": "validation_error", "message": "invalid sim_time"}}, status=400)

    event_id = str(b["event_id"])
    ev = b["event"]
    newly_fulfilled_req = None
    need_topup_req_id = None

    with IDEMPOTENCY_LOCK:
        with transaction.atomic():
            # Deduplication by event_id
            if CallbackEvent.objects.select_for_update().filter(event_id=event_id).exists():
                return JsonResponse({"ok": True}, status=200)

            CallbackEvent.objects.create(
                event_id=event_id,
                event_type="donor_progress",
                request_id=str(b["request_id"]),
                donor_id=str(b["donor_id"]),
                payload=b,
            )

            req = BloodRequest.objects.select_for_update().filter(request_id=str(b["request_id"])).first()
            if not req:
                return JsonResponse({"ok": True}, status=200)

            track, _ = DonorTrack.objects.select_for_update().get_or_create(
                request=req,
                donor_id=str(b["donor_id"]),
                defaults={"state": "accepted"},
            )

            cur_rank = STATE_RANKS.get(track.state, 0)
            is_terminal = track.state in ("donated", "screen_fail", "no_show", "cancelled", "stopped")

            if ev == "en_route":
                if cur_rank < 3 and not is_terminal:
                    track.state = "en_route"
                    track.save()
                    req.en_route += 1
                    req.save()

            elif ev == "arrived":
                if cur_rank < 4 and not is_terminal:
                    track.state = "arrived"
                    track.save()
                    req.arrived += 1
                    req.save()

            elif ev == "screen_pass":
                if cur_rank < 5 and not is_terminal:
                    track.state = "screen_pass"
                    track.save()

            elif ev == "screen_fail":
                track.state = "screen_fail"
                track.save()
                if req.status in ("open", "mobilizing") and req.shortage > 0:
                    active_going = DonorTrack.objects.filter(
                        request=req, state__in=["accepted", "en_route", "arrived", "screen_pass"]
                    ).count()
                    if active_going < req.shortage:
                        need_topup_req_id = req.request_id

            elif ev == "no_show":
                track.state = "no_show"
                track.save()
                if req.status in ("open", "mobilizing") and req.shortage > 0:
                    active_going = DonorTrack.objects.filter(
                        request=req, state__in=["accepted", "en_route", "arrived", "screen_pass"]
                    ).count()
                    if active_going < req.shortage:
                        need_topup_req_id = req.request_id

            elif ev == "donated":
                if track.state != "donated":
                    track.state = "donated"
                    track.donated_sim_min = sim_time
                    track.save()
                    req.fulfilled += 1
                    if req.fulfilled >= req.needed and req.status not in ("cancelled", "expired"):
                        req.status = "fulfilled"
                        newly_fulfilled_req = req
                    req.save()

    if newly_fulfilled_req:
        stop_donor_outreach(newly_fulfilled_req, template="not_needed")
    elif need_topup_req_id:
        send_donor_invitations(need_topup_req_id, max_cap=8)

    process_stock_arrivals(sim_time)
    return JsonResponse({"ok": True}, status=200)
