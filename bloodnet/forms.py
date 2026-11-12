import re
from django import forms
from .models import AppointmentSlot, StudentAppointment

PERSIAN_TO_ENGLISH_DIGITS = str.maketrans(
    "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
    "01234567890123456789",
)

VALID_FACULTIES = [
    ("دانشکده فنی و مهندسی", "دانشکده فنی و مهندسی"),
    ("دانشکده علوم پایه", "دانشکده علوم پایه"),
    ("دانشکده ادبیات و علوم انسانی", "دانشکده ادبیات و علوم انسانی"),
    ("دانشکده کشاورزی و منابع طبیعی", "دانشکده کشاورزی و منابع طبیعی"),
    ("دانشکده دامپزشکی", "دانشکده دامپزشکی"),
]


def normalize_digits(value: str) -> str:
    if not value:
        return ""
    return str(value).strip().translate(PERSIAN_TO_ENGLISH_DIGITS)


class StudentAppointmentForm(forms.Form):
    fullName = forms.CharField(
        required=True,
        max_length=120,
        error_messages={
            "required": "لطفاً نام و نام خانوادگی خود را وارد کنید.",
            "max_length": "نام و نام خانوادگی نمی‌تواند بیش از ۱۲۰ کاراکتر باشد.",
        },
    )
    studentId = forms.CharField(
        required=True,
        max_length=32,
        error_messages={
            "required": "وارد کردن شماره دانشجویی ۹ رقمی الزامی است.",
        },
    )
    faculty = forms.ChoiceField(
        required=True,
        choices=VALID_FACULTIES,
        error_messages={
            "required": "لطفاً دانشکده محل تحصیل را انتخاب کنید.",
            "invalid_choice": "دانشکده انتخاب‌شده معتبر نیست.",
        },
    )
    slot = forms.CharField(
        required=False,
        max_length=64,
    )
    action = forms.CharField(
        required=False,
        max_length=32,
    )

    def clean_fullName(self):
        val = (self.cleaned_data.get("fullName") or "").strip()
        if len(val) < 3:
            raise forms.ValidationError("نام و نام خانوادگی باید حداقل ۳ حرف باشد.")
        return val

    def clean_studentId(self):
        raw = self.cleaned_data.get("studentId") or ""
        normalized = normalize_digits(raw)
        if not re.fullmatch(r"\d{9}", normalized):
            raise forms.ValidationError("شماره دانشجویی باید دقیقاً ۹ رقم عددی باشد.")
        return normalized

    def clean(self):
        cleaned = super().clean()
        action = (cleaned.get("action") or "").strip()
        slot_val = (cleaned.get("slot") or "").strip()
        student_id = cleaned.get("studentId")

        if student_id:
            existing_active = StudentAppointment.objects.filter(
                student_id=student_id,
                status__in=["confirmed", "checked_in", "waitlist"],
            ).first()
            if existing_active:
                self.add_error(
                    "studentId",
                    f"برای این شماره دانشجویی قبلاً نوبت فعال با کد پیگیری {existing_active.tracking_code} ثبت شده است.",
                )
                return cleaned

        if action != "waitlist":
            if not slot_val:
                self.add_error("slot", "لطفاً یک بازه زمانی معتبر برای اهدای خون انتخاب کنید.")
            else:
                slot_obj = AppointmentSlot.objects.filter(time_label=slot_val).first()
                if not slot_obj:
                    slot_obj = AppointmentSlot.objects.filter(code=slot_val).first()
                if not slot_obj:
                    self.add_error("slot", "بازه زمانی انتخاب‌شده در سامانه وجود ندارد.")
                elif not slot_obj.is_available:
                    self.add_error("slot", f"ظرفیت بازه زمانی «{slot_obj.time_label}» تکمیل شده است.")
                else:
                    cleaned["slot_obj"] = slot_obj

        return cleaned
