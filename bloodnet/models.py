from django.db import models


class BloodRequest(models.Model):
    STATUS_CHOICES = [
        ("pending_review", "Pending Review"),
        ("open", "Open"),
        ("mobilizing", "Mobilizing"),
        ("partially_fulfilled", "Partially Fulfilled"),
        ("fulfilled", "Fulfilled"),
        ("cancelled", "Cancelled"),
        ("expired", "Expired"),
    ]

    BLOOD_GROUP_CHOICES = [
        ("O+", "O+"),
        ("A+", "A+"),
        ("B+", "B+"),
        ("AB+", "AB+"),
        ("O-", "O-"),
        ("A-", "A-"),
        ("B-", "B-"),
        ("AB-", "AB-"),
    ]

    PRODUCT_CHOICES = [
        ("red_cells", "Red Cells"),
        ("platelets", "Platelets"),
        ("plasma", "Plasma"),
    ]

    URGENCY_CHOICES = [
        ("critical", "Critical"),
        ("urgent", "Urgent"),
        ("planned", "Planned"),
    ]

    request_id = models.CharField(max_length=64, unique=True, db_index=True)
    hospital_id = models.CharField(max_length=32, db_index=True)
    blood_group = models.CharField(max_length=8, choices=BLOOD_GROUP_CHOICES)
    product = models.CharField(max_length=32, choices=PRODUCT_CHOICES)
    urgency = models.CharField(max_length=32, choices=URGENCY_CHOICES)
    needed = models.PositiveIntegerField()
    note = models.CharField(max_length=500, blank=True, default="")

    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default="open", db_index=True)
    confirmed = models.PositiveIntegerField(default=0)
    en_route = models.PositiveIntegerField(default=0)
    arrived = models.PositiveIntegerField(default=0)
    fulfilled = models.PositiveIntegerField(default=0)
    stock_inflight = models.PositiveIntegerField(default=0)

    created_sim_min = models.FloatField(default=0.0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "bloodnet_requests"
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(needed__gte=1, needed__lte=20),
                name="check_needed_units_range",
            ),
            models.CheckConstraint(
                condition=models.Q(confirmed__gte=0),
                name="check_confirmed_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(en_route__gte=0),
                name="check_en_route_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(arrived__gte=0),
                name="check_arrived_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(fulfilled__gte=0),
                name="check_fulfilled_non_negative",
            ),
        ]

    def __str__(self):
        return f"{self.request_id} ({self.hospital_id} - {self.blood_group} {self.product} x{self.needed})"

    @property
    def shortage(self):
        return max(0, self.needed - self.fulfilled - self.stock_inflight)


class StockDispatch(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("dispatched", "Dispatched"),
        ("failed", "Failed"),
    ]

    dispatch_id = models.CharField(max_length=64, unique=True, db_index=True)
    request = models.ForeignKey(
        BloodRequest,
        on_delete=models.CASCADE,
        related_name="dispatches",
    )
    center_id = models.CharField(max_length=32, db_index=True)
    blood_group = models.CharField(max_length=8)
    product = models.CharField(max_length=32)
    units = models.PositiveIntegerField()
    hospital_id = models.CharField(max_length=32)
    recipient_blood_group = models.CharField(max_length=8)

    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default="pending", db_index=True)
    eta_sim_min = models.FloatField(null=True, blank=True)
    response_code = models.IntegerField(null=True, blank=True)
    error_message = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "bloodnet_stock_dispatches"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.dispatch_id} ({self.center_id} -> {self.units} {self.blood_group} {self.product} [{self.status}])"


class IdempotencyRecord(models.Model):
    key = models.CharField(max_length=128, unique=True, db_index=True)
    body_hash = models.CharField(max_length=64)
    response_code = models.IntegerField(default=201)
    response_body = models.JSONField()
    request = models.ForeignKey(
        BloodRequest,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="idempotency_records",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "bloodnet_idempotency_records"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.key} -> {self.response_code}"


class DonorInvitation(models.Model):
    notification_id = models.CharField(max_length=64, unique=True, db_index=True)
    request = models.ForeignKey(
        BloodRequest,
        on_delete=models.CASCADE,
        related_name="donor_invitations",
    )
    donor_id = models.CharField(max_length=32, db_index=True)
    template = models.CharField(max_length=32, default="request_wave")
    status = models.CharField(max_length=32, default="queued")
    created_sim_min = models.FloatField(default=0.0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "bloodnet_donor_invitations"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.notification_id} -> {self.donor_id} ({self.status})"


class DonorTrack(models.Model):
    STATE_CHOICES = [
        ("invited", "Invited"),
        ("accepted", "Accepted"),
        ("declined", "Declined"),
        ("en_route", "En Route"),
        ("arrived", "Arrived"),
        ("screen_pass", "Screen Pass"),
        ("screen_fail", "Screen Fail"),
        ("donated", "Donated"),
        ("no_show", "No Show"),
        ("cancelled", "Cancelled"),
        ("stopped", "Stopped"),
    ]

    request = models.ForeignKey(
        BloodRequest,
        on_delete=models.CASCADE,
        related_name="donor_tracks",
    )
    donor_id = models.CharField(max_length=32, db_index=True)
    state = models.CharField(max_length=32, choices=STATE_CHOICES, default="invited", db_index=True)
    notification_id = models.CharField(max_length=64, blank=True, default="")
    accepted_sim_min = models.FloatField(null=True, blank=True)
    donated_sim_min = models.FloatField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "bloodnet_donor_tracks"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["request", "donor_id"], name="unique_request_donor_track"),
        ]

    def __str__(self):
        return f"{self.donor_id} @ {self.request.request_id}: {self.state}"


class CallbackEvent(models.Model):
    event_id = models.CharField(max_length=64, unique=True, db_index=True)
    event_type = models.CharField(max_length=32)
    request_id = models.CharField(max_length=64, blank=True, default="")
    donor_id = models.CharField(max_length=32, blank=True, default="")
    payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "bloodnet_callback_events"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.event_id} ({self.event_type})"


class AppointmentSlot(models.Model):
    code = models.CharField(max_length=32, unique=True, db_index=True)
    time_label = models.CharField(max_length=64, unique=True)
    subtitle = models.CharField(max_length=120, default="")
    capacity = models.PositiveIntegerField(default=10)
    booked_count = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    display_order = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "bloodnet_appointment_slots"
        ordering = ["display_order", "id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(booked_count__lte=models.F("capacity")),
                name="check_slot_booked_lte_capacity",
            ),
        ]

    def __str__(self):
        return f"{self.time_label} ({self.remaining_capacity}/{self.capacity})"

    @property
    def remaining_capacity(self):
        return max(0, self.capacity - self.booked_count)

    @property
    def is_available(self):
        return self.is_active and self.remaining_capacity > 0


class StudentAppointment(models.Model):
    STATUS_CHOICES = [
        ("invitation_accepted", "Invitation Accepted"),
        ("confirmed", "Booked / Confirmed"),
        ("waitlist", "Waitlisted"),
        ("checked_in", "Checked In / Attendance Recorded"),
        ("completed", "Donation Completed"),
        ("cancelled", "Cancelled"),
    ]

    tracking_code = models.CharField(max_length=32, unique=True, db_index=True)
    full_name = models.CharField(max_length=120)
    student_id = models.CharField(max_length=16, db_index=True)
    faculty = models.CharField(max_length=120)
    blood_group = models.CharField(max_length=8, default="O+")
    slot = models.ForeignKey(
        AppointmentSlot,
        on_delete=models.PROTECT,
        related_name="appointments",
        null=True,
        blank=True,
    )
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default="confirmed", db_index=True)
    invitation_accepted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "bloodnet_student_appointments"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.tracking_code} - {self.full_name} ({self.student_id}) [{self.status}]"

