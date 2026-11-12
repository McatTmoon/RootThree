# DECLARED.md — قابلیت‌های اعلان‌شده تیم Root Three (BloodNet)

این سند مطابق بخش ۷ و ۸ صورت‌مسئله (`Challenge_Brief.pdf`) و راهنمای داوری (`Judging-Brief-FA.pdf`)، تمامی قابلیت‌های پیاده‌سازی‌شده و آماده ارزیابی در مخزن را به‌صورت دقیق و قابل ردیابی در کد معرفی می‌کند.

---

## ۱. بخش بک‌اند و مهندسی (۷۰ امتیاز پایه)

### ۱.۱ قرارداد API، احراز هویت و Idempotency (`bloodnet/views.py`, `bloodnet/models.py`)
- **`GET /health`**: بازگرداندن وضعیت سلامت سرویس (`{"ok": true}` با کد `200`).
- **`POST /requests`**:
  - احراز هویت با توکن بیمارستان (`Bearer hospital-token` قابل پیکربندی از متغیر محیطی `HOSPITAL_TOKEN`).
  - بررسی اجباری هدر `Idempotency-Key` (۱ تا ۱۲۸ کاراکتر).
  - محاسبه هش SHA-256 بدنه درخواست (`body_hash`):
    - تکرار همان کلید با همان بدنه $\leftarrow$ بازپخش پاسخ ذخیره‌شده با کد `200 OK` بدون ایجاد رکورد یا تخصیص مجدد.
    - تکرار همان کلید با بدنه متفاوت $\leftarrow$ خطای `422 Unprocessable Entity` (`idempotency_key_reuse`).
  - مدیریت هم‌زمانی (Concurrency) با قفل سطح برنامه و تراکنش اتمیک دیتابیس (`select_for_update`)؛ تضمین ایجاد دقیقاً ۱ درخواست در ۲۰ درخواست هم‌زمان با کلید یکسان.
  - اعتبارسنجی دقیق فیلدها، گروه خونی، فرآورده (`red_cells`, `platelets`, `plasma`)، فوریت (`critical`, `urgent`, `planned`) و بازه واحدها (`1..20`).
  - بررسی ثبت‌بودن بیمارستان در `participant_kit/hospitals.csv` و رد بیمارستان‌های ناشناس (مانند `H98`) با کد `404 Not Found` (`unknown_hospital`).

### ۱.۲ مدیریت موجودی مراکز، سازگاری و FEFO (`bloodnet/inventory.py`, `bloodnet/compat.py`)
- بارگذاری پویا و اجرای کامل ماتریس سازگاری از `participant_kit/compat.yaml` برای هر سه فرآورده (`red_cells`, `platelets`, `plasma`).
- استعلام موجودی زنده از سرویس محلی Inventory (`GET /inventory`).
- حذف موجودی‌های منقضی‌شده بر اساس ساعت رسمی شبیه‌سازی (`expires_sim_min <= sim_time`).
- مرتب‌سازی و تخصیص بر اساس **FEFO (First-Expiry-First-Out)**: اولویت با نزدیک‌ترین تاریخ انقضا.
- ثبت پایدار تلاش‌های ارسال در جدول `StockDispatch` با شناسه یکتای `dispatch_id` پیش از فراخوانی شبکه (بدون نگه‌داشتن قفل تراکنش SQLite در حین فراخوانی HTTP).
- پشتیبانی از تلاش مجدد (Bounded Retry) برای کدهای `429` و `503` با همان `dispatch_id` جهت جلوگیری از کسر دوبل موجودی.
- تبدیل خودکار واحدهای در راه (`stock_inflight`) به تأمین‌شده (`fulfilled`) به محض رسیدن زمان شبیه‌سازی به `eta_sim_min` (`process_stock_arrivals`).

### ۱.۳ ایمنی اهداکنندگان، شرایط اهدا و تعلیق‌های موقت (`bloodnet/donors.py`)
- بررسی کامل شرایط پایه طبق `participant_kit/rules.yaml`:
  - عدم محرومیت دائم (`permanently_excluded == 0`)
  - سن بین `18` تا `65` سال و وزن حداقل `50` کیلوگرم
  - رعایت فاصله حداقل بین دو اهدا: خون کامل مردان `60` روز، زنان `90` روز، پلاکت و پلاسما `14` روز، و فاصله بین دو نوع فرآورده متفاوت (`cross_block`) `14` روز.
- بررسی تاریخچه رویدادهای تعلیق موقت در `participant_kit/donor_events.csv`:
  - رویداد `tattoo` (تعلیق ۱۸۰ روزه) و `travel_risk` (تعلیق ۹۰ روزه) تا زمان `defer_until` با در نظر گرفتن آخرین رویداد هر اهداکننده.
- رعایت قانون **A2 (یک تعهد فعال برای هر اهداکننده)** و حذف اهداکنندگانی که در طول همان اجرای شبیه‌سازی اهدا انجام داده‌اند (`donated` / `screen_pass` / `accepted` / `en_route` / `arrived`) جهت صفر نگه داشتن خطای ایمنی (`ineligible_notifications = 0`).

### ۱.۴ پردازش Callbackها، ماشین وضعیت و جلوگیری از Overfill (`bloodnet/callbacks.py`)
- پیاده‌سازی کامل مسیرهای:
  - `POST /callbacks/gateway-status`
  - `POST /callbacks/donor-response`
  - `POST /callbacks/donor-progress`
- حذف تکراری‌ها (Deduplication) بر اساس `event_id` یکتا در جدول `CallbackEvent`.
- ماشین وضعیت یک‌طرفه (Forward-Only State Machine) با رتبه‌بندی مراحل (`invited` $\to$ `accepted` $\to$ `en_route` $\to$ `arrived` $\to$ `screen_pass` $\to$ `donated`) که از عقب‌گرد وضعیت در رویدادهای خارج از ترتیب (Out-of-Order) جلوگیری می‌کند.
- شمارش واحد تأمین‌شده (`fulfilled += 1`) **صرفاً پس از دریافت رویداد معتبر `donated`** (قبول دعوت تنها شمارنده `confirmed` را افزایش می‌دهد).
- کنترل سقف تأیید هم‌زمان (`confirmed`) و ارسال خودکار پیام `not_needed` / `cancelled` به اهداکنندگان در انتظار پس از تکمیل یا لغو درخواست جهت کمینه‌سازی `overfill_units`.

### ۱.۵ تشخیص ترافیک سوءاستفاده (Abuse) و چرخه تأیید/اصلاح/لغو (`bloodnet/views.py`)
- تشخیص خودکار درخواست‌های مشکوک و حملات Burst (درخواست‌های بحرانی با حجم غیرعادی `units >= 7` یا ارسال رگباری چند درخواست از یک بیمارستان در پنجره زمانی کوتاه شبیه‌سازی) و قرار دادن آن‌ها در وضعیت `pending_review` بدون مصرف موجودی یا ارسال پیامک تا زمان تأیید هماهنگ‌کننده (`POST /requests/{id}/approve`).
- پشتیبانی کامل از `POST /requests/{id}/approve` (با `Bearer coordinator-token`)، `POST /requests/{id}/amend` و `POST /requests/{id}/cancel`.

---

## ۲. ماژول هوشمند اختیاری (۲۰ امتیاز شفاهی / ۱۰ امتیاز هارنس)

### امتیازدهی هوشمند اهداکنندگان (Expected Timely Yield Scorer) — کاملاً آفلاین و محلی
- **محل پیاده‌سازی:** تابع `score_donor_candidate` و بارگذار بیزین در `bloodnet/donors.py`.
- **ورودی‌ها:**
  1. تاریخچه ۲۰۷٬۴۸۶ پاسخ قبلی اهداکنندگان در `participant_kit/history/responses.csv`.
  2. ماتریس‌های زمان سفر `travel_area_to_center.csv` و `travel_center_to_hospital.csv`.
  3. ساعات کاری مراکز اهدای خون در `centers.csv` (`MC1` شبانه‌روزی ۰ تا ۲۴، `MC2..MC5` ساعت ۸ تا ۲۰).
  4. بازه ساعات سکوت هر اهداکننده (`quiet_start_hour`, `quiet_end_hour`) و تعداد پیامک‌های ۹۰ روز اخیر (`notified_90d`) در `donors.csv`.
  5. زمان فعلی شبیه‌سازی (`sim_time`) و مهلت SLA درخواست (`critical: 90m`, `urgent: 240m`, `planned: 1440m`).
- **منطق و خروجی:**
  - محاسبه احتمال تجربی پذیرش و اهدا با هموارسازی بیزین (Bayesian Smoothing):
    $$P_{\text{rel}}(d) = \frac{\text{donated}_d + 0.5 \cdot \text{accepted}_d + 1}{\text{notified}_d + 3}$$
  - محاسبه زمان واقعی تأمین انتها-به-انتها (End-to-End Supply ETA):
    $$\text{ETA} = t_{\text{response}} + t_{\text{area}\to\text{center}} + t_{\text{wait\_open}} + t_{\text{visit}}(\text{product}) + t_{\text{proc}}(20\text{m}) + t_{\text{center}\to\text{hospital}}$$
  - جریمه اهداکنندگانی که در ساعت سکوت قرار دارند یا مرکز نزدیکشان بسته است و ETA آن‌ها از SLA درخواست فراتر می‌رود.
  - خروجی: امتیاز ترکیبی (Composite Cost) که اهداکنندگان واجد شرایط را به ترتیب بالاترین شانس رسیدن خون پیش از مهلت SLA رتبه‌بندی می‌کند.
- **محدودیت‌های شناخته‌شده:**
  - مدل بیزین بر اساس تاریخچه گذشته (`history/responses.csv`) کالیبره می‌شود؛ برای اهداکنندگان بدون سابقه قبلی از مقدار پیش‌فرض یکنواخت ($0.35$) استفاده می‌کند.
  - زمان انتظار صف تخت‌های مراکز (`beds`) به صورت استاتیک از ظرفیت پایه مرکز تقریب زده می‌شود زیرا وضعیت لحظه‌ای تخت‌های هر مرکز در API شبیه‌ساز منتشر نمی‌شود.

---

## ۳. بخش فرانت‌اند و جریان کاربری (۳۰ امتیاز پایه)
- رابط کاربری فارسی و راست‌چین (RTL) متصل به دیتابیس SQLite جنگو.
- صفحات اهداکننده/دانشجو شامل: صفحه اصلی، دعوت‌نامه اهدا، فرم ثبت‌نام و نوبت‌دهی (با اعتبارسنجی سمت سرور، توکن CSRF، جلوگیری از رزرو بیش از ظرفیت و صدور کد رهگیری یکتا) و صفحه پیگیری وضعیت نوبت/اهدا.
