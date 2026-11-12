import base64
import random
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_http_methods

from .forms import StudentAppointmentForm, normalize_digits
from .models import AppointmentSlot, BloodRequest, DonorTrack, StockDispatch, StudentAppointment
from .views import IDEMPOTENCY_LOCK

# 1x1 Crimson/Burgundy PNG fallback + SVG logo
LOGO_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="64" height="64">
  <rect width="64" height="64" rx="14" fill="#6b0119"/>
  <path d="M32 10C32 10 16 28.5 16 40C16 48.8 23.2 56 32 56C40.8 56 48 48.8 48 40C48 28.5 32 10 32 10Z" fill="#ffffff"/>
  <path d="M30 31V25H34V31H40V35H34V41H30V35H24V31H30Z" fill="#6b0119"/>
</svg>"""

DEFAULT_SLOTS = [
    {
        "code": "slot-0830",
        "time_label": "۰۸:۳۰ - ۰۹:۱۵",
        "subtitle": "پذیرش افتتاحیه پایگاه",
        "capacity": 10,
        "booked_count": 10,
        "is_active": True,
        "display_order": 1,
    },
    {
        "code": "slot-0915",
        "time_label": "۰۹:۱۵ - ۱۰:۰۰",
        "subtitle": "نوبت شیفت اول صبح",
        "capacity": 10,
        "booked_count": 7,
        "is_active": True,
        "display_order": 2,
    },
    {
        "code": "slot-1000",
        "time_label": "۱۰:۰۰ - ۱۰:۴۵",
        "subtitle": "اوج پذیرش سالن اصلی",
        "capacity": 15,
        "booked_count": 5,
        "is_active": True,
        "display_order": 3,
    },
    {
        "code": "slot-1045",
        "time_label": "۱۰:۴۵ - ۱۱:۳۰",
        "subtitle": "رزرو گروهی انجمن علمی",
        "capacity": 10,
        "booked_count": 10,
        "is_active": True,
        "display_order": 4,
    },
    {
        "code": "slot-1130",
        "time_label": "۱۱:۳۰ - ۱۲:۱۵",
        "subtitle": "نوبت پیش از ظهر",
        "capacity": 12,
        "booked_count": 4,
        "is_active": True,
        "display_order": 5,
    },
    {
        "code": "slot-1215",
        "time_label": "۱۲:۱۵ - ۱۳:۰۰",
        "subtitle": "نوبت ظهرگاهی",
        "capacity": 10,
        "booked_count": 5,
        "is_active": True,
        "display_order": 6,
    },
    {
        "code": "slot-1300",
        "time_label": "۱۳:۰۰ - ۱۳:۴۵",
        "subtitle": "پایان شیفت خون‌گیری",
        "capacity": 8,
        "booked_count": 8,
        "is_active": True,
        "display_order": 7,
    },
]


def ensure_seed_data():
    """Ensure synthetic Lorestan University time slots and sample student bookings exist."""
    if AppointmentSlot.objects.count() == 0:
        with transaction.atomic():
            if AppointmentSlot.objects.count() == 0:
                for item in DEFAULT_SLOTS:
                    AppointmentSlot.objects.create(**item)

    if StudentAppointment.objects.count() == 0:
        with transaction.atomic():
            if StudentAppointment.objects.count() == 0:
                slot_1000 = AppointmentSlot.objects.filter(code="slot-1000").first()
                slot_0915 = AppointmentSlot.objects.filter(code="slot-0915").first()
                slot_1130 = AppointmentSlot.objects.filter(code="slot-1130").first()
                StudentAppointment.objects.create(
                    tracking_code="BLD-1403-8721",
                    full_name="سروش دلفان‌نیا",
                    student_id="993122341",
                    faculty="دانشکده فنی و مهندسی",
                    blood_group="O+",
                    slot=slot_1000,
                    status="confirmed",
                    invitation_accepted=True,
                )
                StudentAppointment.objects.create(
                    tracking_code="BLD-1403-1002",
                    full_name="زهرا بیرانوند",
                    student_id="400112233",
                    faculty="دانشکده علوم پایه",
                    blood_group="A+",
                    slot=slot_0915,
                    status="checked_in",
                    invitation_accepted=True,
                )
                StudentAppointment.objects.create(
                    tracking_code="BLD-1403-1003",
                    full_name="امیرحسین کرمی",
                    student_id="401223344",
                    faculty="دانشکده کشاورزی و منابع طبیعی",
                    blood_group="O-",
                    slot=slot_1130,
                    status="completed",
                    invitation_accepted=True,
                )


def _generate_unique_tracking_code():
    for _ in range(50):
        num = random.randint(1000, 9999)
        code = f"BLD-1403-{num}"
        if not StudentAppointment.objects.filter(tracking_code=code).exists():
            return code
    return f"BLD-1403-{random.randint(10000, 99999)}"


@require_http_methods(["GET", "POST"])
def home_page(request):
    """Serve Home page (or delegate if ?page= query param is used)."""
    page_param = request.GET.get("page")
    if page_param == "registration":
        return registration_page(request)
    if page_param == "invitation":
        return invitation_page(request)
    if page_param == "tracking":
        return tracking_page(request)

    ensure_seed_data()
    slots = list(AppointmentSlot.objects.all())
    total_remaining = sum(s.remaining_capacity for s in slots)
    active_requests = list(BloodRequest.objects.all()[:10])
    total_appointments = StudentAppointment.objects.exclude(status="cancelled").count()
    completed_donations = (
        StudentAppointment.objects.filter(status="completed").count()
        + DonorTrack.objects.filter(state="donated").count()
    )

    context = {
        "slots": slots,
        "total_remaining": total_remaining,
        "active_requests": active_requests,
        "total_appointments": total_appointments,
        "completed_donations": completed_donations,
    }
    return render(request, "bloodnet/home.html", context)


@require_http_methods(["GET", "POST"])
def registration_page(request):
    """Serve student blood donation slot registration page with CSRF & server-side validation."""
    ensure_seed_data()
    slots = list(AppointmentSlot.objects.all())
    first_available_slot = next((s.time_label for s in slots if s.is_available), "")
    default_slot = "۱۰:۰۰ - ۱۰:۴۵"
    if not any(s.time_label == default_slot and s.is_available for s in slots):
        default_slot = first_available_slot

    saved_appointment = None
    form_errors = []
    selected_slot_label = default_slot
    invited = (
        request.GET.get("invited") == "1"
        or request.POST.get("invited") == "1"
        or bool(request.session.get("invitation_accepted"))
    )

    if request.method == "POST":
        form = StudentAppointmentForm(request.POST)
        selected_slot_label = request.POST.get("slot") or default_slot
        if form.is_valid():
            full_name = form.cleaned_data["fullName"]
            student_id = form.cleaned_data["studentId"]
            faculty = form.cleaned_data["faculty"]
            action = form.cleaned_data.get("action") or "book"

            with IDEMPOTENCY_LOCK:
                with transaction.atomic():
                    # Re-check duplicate active booking inside lock
                    dup = StudentAppointment.objects.select_for_update().filter(
                        student_id=student_id,
                        status__in=["confirmed", "checked_in", "waitlist"],
                    ).first()
                    if dup:
                        form.add_error(
                            "studentId",
                            f"برای شماره دانشجویی {student_id} قبلاً نوبت فعال ({dup.tracking_code}) ثبت شده است.",
                        )
                    elif action == "waitlist":
                        code = _generate_unique_tracking_code()
                        saved_appointment = StudentAppointment.objects.create(
                            tracking_code=code,
                            full_name=full_name,
                            student_id=student_id,
                            faculty=faculty,
                            blood_group="O+",
                            slot=None,
                            status="waitlist",
                            invitation_accepted=invited,
                        )
                        request.session["last_tracking_code"] = code
                    else:
                        slot_label = form.cleaned_data["slot_obj"].time_label
                        locked_slot = AppointmentSlot.objects.select_for_update().filter(
                            time_label=slot_label
                        ).first()
                        if not locked_slot or not locked_slot.is_available:
                            form.add_error(
                                "slot",
                                "متأسفانه ظرفیت این بازه زمانی لحظاتی پیش تکمیل شد. لطفاً بازه دیگری انتخاب کنید.",
                            )
                        else:
                            locked_slot.booked_count += 1
                            locked_slot.save()
                            code = _generate_unique_tracking_code()
                            saved_appointment = StudentAppointment.objects.create(
                                tracking_code=code,
                                full_name=full_name,
                                student_id=student_id,
                                faculty=faculty,
                                blood_group="O+",
                                slot=locked_slot,
                                status="confirmed",
                                invitation_accepted=invited,
                            )
                            request.session["last_tracking_code"] = code
                            selected_slot_label = locked_slot.time_label

        if not saved_appointment:
            for field, errors in form.errors.items():
                for err in errors:
                    form_errors.append(err)
        slots = list(AppointmentSlot.objects.all())
    else:
        form = StudentAppointmentForm(
            initial={
                "faculty": "دانشکده فنی و مهندسی",
                "slot": default_slot,
            }
        )

    context = {
        "form": form,
        "form_errors": form_errors,
        "slots": slots,
        "selected_slot_label": selected_slot_label,
        "saved_appointment": saved_appointment,
        "invited": invited,
    }
    status_code = 201 if saved_appointment else (400 if request.method == "POST" else 200)
    return render(request, "bloodnet/registration.html", context, status=status_code)


@require_http_methods(["GET", "POST"])
def invitation_page(request):
    """Serve student campaign invitation page with distinct acceptance/decline tracking."""
    ensure_seed_data()
    invitation_state = request.session.get("invitation_status", "active")
    state_param = request.GET.get("state")
    if state_param in ("active", "accepted", "declined", "expired"):
        invitation_state = state_param

    if request.method == "POST":
        resp_action = (request.POST.get("response") or "").strip()
        if resp_action == "accept":
            invitation_state = "accepted"
            request.session["invitation_status"] = "accepted"
            request.session["invitation_accepted"] = True
        elif resp_action == "decline":
            invitation_state = "declined"
            request.session["invitation_status"] = "declined"
            request.session["invitation_accepted"] = False
        elif resp_action == "expired":
            invitation_state = "expired"
        elif resp_action == "reset":
            invitation_state = "active"
            request.session["invitation_status"] = "active"

    registered_count = 140 + StudentAppointment.objects.exclude(status="cancelled").count()
    completed_count = 105 + StudentAppointment.objects.filter(status="completed").count()

    context = {
        "invitation_state": invitation_state,
        "registered_count": registered_count,
        "completed_count": completed_count,
    }
    return render(request, "bloodnet/invitation.html", context)


@require_http_methods(["GET", "POST"])
def tracking_page(request, tracking_code=None):
    """Serve database-backed appointment tracking & stage progression page."""
    ensure_seed_data()

    query = (
        tracking_code
        or request.GET.get("code")
        or request.GET.get("q")
        or request.POST.get("code")
        or request.POST.get("q")
        or ""
    ).strip()

    # Handle POST state mutations (cancel, check_in, complete) backed by DB
    if request.method == "POST" and request.POST.get("action") in ("cancel", "check_in", "complete"):
        target_code = (request.POST.get("tracking_code") or query).strip()
        action = request.POST.get("action")
        with IDEMPOTENCY_LOCK:
            with transaction.atomic():
                appt = StudentAppointment.objects.select_for_update().filter(
                    tracking_code__iexact=target_code
                ).first()
                if appt:
                    if action == "cancel" and appt.status != "cancelled":
                        if appt.status == "confirmed" and appt.slot_id:
                            slot_obj = AppointmentSlot.objects.select_for_update().filter(id=appt.slot_id).first()
                            if slot_obj and slot_obj.booked_count > 0:
                                slot_obj.booked_count -= 1
                                slot_obj.save()
                        appt.status = "cancelled"
                        appt.save()
                    elif action == "check_in" and appt.status == "confirmed":
                        appt.status = "checked_in"
                        appt.save()
                    elif action == "complete" and appt.status in ("confirmed", "checked_in"):
                        appt.status = "completed"
                        appt.save()
                    query = appt.tracking_code

    appointment = None
    tracking_state = "confirmed"
    error_message = ""

    if query:
        norm_q = normalize_digits(query)
        appointment = StudentAppointment.objects.select_related("slot").filter(
            tracking_code__iexact=query
        ).first()
        if not appointment and norm_q.isdigit():
            appointment = StudentAppointment.objects.select_related("slot").filter(
                student_id=norm_q
            ).first()

        if appointment:
            tracking_state = (
                "confirmed"
                if appointment.status in ("confirmed", "waitlist", "invitation_accepted")
                else appointment.status
            )
        else:
            tracking_state = "not_found"
            error_message = f"نوبتی با مشخصات «{query}» در پایگاه داده دانشگاه لرستان یافت نشد. لطفاً کد پیگیری یا شماره دانشجویی را بررسی کنید."
    else:
        # Default view: load user's last booked code in session, or sample DB record BLD-1403-8721
        default_code = request.session.get("last_tracking_code") or "BLD-1403-8721"
        appointment = StudentAppointment.objects.select_related("slot").filter(
            tracking_code__iexact=default_code
        ).first()
        if not appointment:
            appointment = StudentAppointment.objects.select_related("slot").first()
        if appointment:
            query = appointment.tracking_code
            tracking_state = (
                "confirmed"
                if appointment.status in ("confirmed", "waitlist", "invitation_accepted")
                else appointment.status
            )
        else:
            tracking_state = "not_found"

    context = {
        "appointment": appointment,
        "tracking_state": tracking_state,
        "search_query": query,
        "error_message": error_message,
    }
    status_code = 404 if (query and not appointment) else 200
    return render(request, "bloodnet/tracking.html", context, status=status_code)


@require_GET
def serve_logo_asset(request):
    """Serve the BloodNet LU SVG logo for both /images/logo.png and static paths."""
    return HttpResponse(LOGO_SVG, content_type="image/svg+xml")
