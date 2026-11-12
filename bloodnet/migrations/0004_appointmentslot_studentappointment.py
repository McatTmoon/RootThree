from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("bloodnet", "0003_callbackevent_donorinvitation_donortrack"),
    ]

    operations = [
        migrations.CreateModel(
            name="AppointmentSlot",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.CharField(db_index=True, max_length=32, unique=True)),
                ("time_label", models.CharField(max_length=64, unique=True)),
                ("subtitle", models.CharField(default="", max_length=120)),
                ("capacity", models.PositiveIntegerField(default=10)),
                ("booked_count", models.PositiveIntegerField(default=0)),
                ("is_active", models.BooleanField(default=True)),
                ("display_order", models.PositiveIntegerField(default=0)),
            ],
            options={
                "db_table": "bloodnet_appointment_slots",
                "ordering": ["display_order", "id"],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("booked_count__lte", models.F("capacity"))),
                        name="check_slot_booked_lte_capacity",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="StudentAppointment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("tracking_code", models.CharField(db_index=True, max_length=32, unique=True)),
                ("full_name", models.CharField(max_length=120)),
                ("student_id", models.CharField(db_index=True, max_length=16)),
                ("faculty", models.CharField(max_length=120)),
                ("blood_group", models.CharField(default="O+", max_length=8)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("invitation_accepted", "Invitation Accepted"),
                            ("confirmed", "Booked / Confirmed"),
                            ("waitlist", "Waitlisted"),
                            ("checked_in", "Checked In / Attendance Recorded"),
                            ("completed", "Donation Completed"),
                            ("cancelled", "Cancelled"),
                        ],
                        db_index=True,
                        default="confirmed",
                        max_length=32,
                    ),
                ),
                ("invitation_accepted", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "slot",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="appointments",
                        to="bloodnet.appointmentslot",
                    ),
                ),
            ],
            options={
                "db_table": "bloodnet_student_appointments",
                "ordering": ["-created_at"],
            },
        ),
    ]
