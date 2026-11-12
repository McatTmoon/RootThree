"use strict";

if (window.tailwind) {
  tailwind.config = { darkMode: "class", theme: { extend: { "colors": { "on-surface-variant": "#574142", "tertiary-fixed-dim": "#ffb68e", "primary-container": "#8b1e2d", "surface-container-low": "#f1f4f8", "inverse-primary": "#ffb3b4", "on-secondary-fixed": "#00210c", "tertiary": "#562300", "on-background": "#181c1f", "tertiary-container": "#7a3400", "surface-bright": "#f7fafd", "on-tertiary-fixed-variant": "#763300", "outline-variant": "#debfbf", "on-primary": "#ffffff", "on-tertiary-container": "#ffa16b", "primary": "#6b0119", "on-primary-fixed-variant": "#881c2b", "surface-container-high": "#e5e8ec", "secondary-fixed-dim": "#80d997", "primary-fixed": "#ffdada", "inverse-surface": "#2d3134", "on-secondary-fixed-variant": "#005228", "outline": "#8b7171", "error-container": "#ffdad6", "surface-container": "#ebeef2", "on-secondary-container": "#0c723b", "on-primary-container": "#ff9da0", "on-tertiary-fixed": "#331200", "on-error": "#ffffff", "error": "#ba1a1a", "tertiary-fixed": "#ffdbca", "surface-tint": "#a93441", "secondary-container": "#99f3af", "surface-variant": "#e0e3e7", "surface": "#f7fafd", "surface-dim": "#d7dade", "surface-container-highest": "#e0e3e7", "primary-fixed-dim": "#ffb3b4", "on-primary-fixed": "#40000b", "secondary-fixed": "#9bf6b1", "on-tertiary": "#ffffff", "secondary": "#016d37", "on-surface": "#181c1f", "on-error-container": "#93000a", "surface-container-lowest": "#ffffff", "background": "#f7fafd", "inverse-on-surface": "#eef1f5", "on-secondary": "#ffffff" }, "borderRadius": { "DEFAULT": "0.125rem", "lg": "0.25rem", "xl": "0.5rem", "full": "0.75rem" }, "spacing": { "margin-desktop": "2.5rem", "gutter": "1rem", "space-lg": "1.5rem", "space-xl": "2.25rem", "space-xs": "0.25rem", "space-sm": "0.5rem", "space-md": "1rem", "gutter-desktop": "1.5rem", "margin": "1rem" }, "fontFamily": { "label-md": ["\"Vazirmatn, Shabnam, Tahoma, sans-serif\""], "body-md": ["\"Vazirmatn, Shabnam, Tahoma, sans-serif\""], "headline-lg": ["\"Vazirmatn, Shabnam, Tahoma, sans-serif\""], "body-sm": ["\"Vazirmatn, Shabnam, Tahoma, sans-serif\""], "headline-md": ["\"Vazirmatn, Shabnam, Tahoma, sans-serif\""], "label-sm": ["\"Vazirmatn, Shabnam, Tahoma, sans-serif\""], "headline-sm": ["\"Vazirmatn, Shabnam, Tahoma, sans-serif\""], "body-lg": ["\"Vazirmatn, Shabnam, Tahoma, sans-serif\""], "display": ["\"Vazirmatn, Shabnam, Tahoma, sans-serif\""], "label-lg": ["\"Vazirmatn, Shabnam, Tahoma, sans-serif\""], "body": ["\"Vazirmatn, Shabnam, Tahoma, sans-serif\""], "headline": ["\"Vazirmatn, Shabnam, Tahoma, sans-serif\""] }, "fontSize": { "label-md": ["12px", { "lineHeight": "18px", "fontWeight": "600" }], "body-md": ["14px", { "lineHeight": "24px", "fontWeight": "400" }], "headline-lg": ["26px", { "lineHeight": "40px", "fontWeight": "700" }], "body-sm": ["12px", { "lineHeight": "20px", "fontWeight": "400" }], "headline-md": ["20px", { "lineHeight": "32px", "fontWeight": "700" }], "label-sm": ["11px", { "lineHeight": "16px", "fontWeight": "500" }], "headline-sm": ["17px", { "lineHeight": "28px", "fontWeight": "600" }], "body-lg": ["16px", { "lineHeight": "28px", "fontWeight": "400" }], "display": ["32px", { "lineHeight": "48px", "fontWeight": "800" }], "label-lg": ["14px", { "lineHeight": "22px", "fontWeight": "600" }] } } } };
}

function initHome() {
  const openBtn = document.getElementById('mobileMenuBtn'); const closeBtn = document.getElementById('closeDrawerBtn'); const drawer = document.getElementById('mobileDrawer'); const backdrop = document.getElementById('drawerBackdrop'); function openMenu() { if(!drawer || !backdrop) return; drawer.classList.remove('translate-x-full'); backdrop.classList.remove('opacity-0', 'pointer-events-none'); backdrop.classList.add('opacity-100'); if(openBtn) openBtn.setAttribute('aria-expanded', 'true'); if(closeBtn) closeBtn.focus(); } function closeMenu() { if(!drawer || !backdrop) return; drawer.classList.add('translate-x-full'); backdrop.classList.remove('opacity-100'); backdrop.classList.add('opacity-0', 'pointer-events-none'); if(openBtn) { openBtn.setAttribute('aria-expanded', 'false'); openBtn.focus(); } } if(openBtn) openBtn.addEventListener('click', openMenu); if(closeBtn) closeBtn.addEventListener('click', closeMenu); if(backdrop) backdrop.addEventListener('click', closeMenu); document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && drawer && !drawer.classList.contains('translate-x-full')) { closeMenu(); } });

  document.querySelector('[data-action="home-1"]')
    .addEventListener("click", (event) => {
      alert('شماره شما با موفقیت در سامانه اطلاع‌رسانی پویش بعدی دانشگاه لرستان ثبت گردید.');
    });
}

function initRegistration() {
  const drawer = document.getElementById('mobile-drawer');
  const openButton = document.getElementById('drawer-open-btn');
  const closeButton = document.getElementById('drawer-close-btn');

  function setDrawerOpen(isOpen) {
    drawer.classList.toggle('hidden', !isOpen);
    openButton.setAttribute('aria-expanded', String(isOpen));
    (isOpen ? closeButton : openButton).focus();
  }

  openButton.setAttribute('aria-expanded', 'false');
  openButton.addEventListener('click', () => setDrawerOpen(true));
  closeButton.addEventListener('click', () => setDrawerOpen(false));
  document.getElementById('drawer-backdrop').addEventListener('click', () => setDrawerOpen(false));
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && !drawer.classList.contains('hidden')) {
      setDrawerOpen(false);
    }
  });

  const form = document.getElementById('donor-form');
  const { fullName, studentId, faculty } = form.elements;
  const group = document.getElementById('slots-group');
  const slots = [...group.querySelectorAll('.slot-btn:not(:disabled)')];
  const feedback = document.getElementById('booking-feedback');

  fullName.required = studentId.required = faculty.required = true;
  studentId.pattern = '[0-9۰-۹٠-٩]{9}';

  const badges = slots.map((slot) => {
    const last = slot.lastElementChild;
    const label = last.matches('span') ? last : last.querySelector('span');
    return { label, original: label.textContent.trim().replace(/^انتخاب شده.*$/, 'قابل انتخاب') };
  });

  let selected;
  function updateSummary() {
    document.getElementById('summary-name').textContent = fullName.value.trim() || 'وارد نشده';
    document.getElementById('summary-faculty').textContent = faculty.value || 'انتخاب نشده';
    document.getElementById('summary-slot').textContent = selected?.dataset.slot || 'انتخاب نشده';
  }

  function choose(slot) {
    selected = slot;
    slots.forEach((item, index) => {
      const active = item === slot;
      item.setAttribute('aria-checked', String(active));
      item.tabIndex = active ? 0 : -1;
      item.classList.toggle('active-slot', active);
      item.classList.toggle('bg-primary-fixed/30', active);
      item.classList.toggle('bg-surface-container-low', !active);
      item.classList.toggle('border-primary/30', active);
      badges[index].label.textContent = active ? 'انتخاب شده ✓' : badges[index].original;
    });
    document.getElementById('active-slot-label').textContent = slot
      ? `انتخاب فعال: ${slot.dataset.slot}`
      : 'بازه‌ای انتخاب نشده';
    feedback.hidden = true;
    updateSummary();
  }

  slots.forEach((slot) => slot.addEventListener('click', () => choose(slot)));
  group.addEventListener('keydown', (event) => {
    const index = slots.indexOf(event.target);
    const directions = { ArrowRight: -1, ArrowLeft: 1, ArrowUp: -1, ArrowDown: 1 };
    if (index < 0 || !Object.hasOwn(directions, event.key)) return;
    event.preventDefault();
    const next = slots[(index + directions[event.key] + slots.length) % slots.length];
    choose(next);
    next.focus();
  });

  choose(slots.find((slot) => slot.getAttribute('aria-checked') === 'true') ?? slots[0]);
  form.addEventListener('input', (event) => {
    event.target.setCustomValidity?.('');
    feedback.hidden = true;
    updateSummary();
  });

  studentId.addEventListener('invalid', () => {
    studentId.setCustomValidity('شماره دانشجویی باید ۹ رقم باشد.');
  });

  form.addEventListener('submit', (event) => {
    event.preventDefault();
    if (!fullName.value.trim()) {
      fullName.setCustomValidity('نام و نام خانوادگی را وارد کن.');
      fullName.reportValidity();
      return;
    }

    feedback.hidden = false;
    if (event.submitter?.value === 'waitlist') {
      feedback.textContent = 'فرم فهرست انتظار معتبر است. ارسال درخواست نیاز به اتصال Django دارد.';
    } else if (!selected) {
      feedback.textContent = 'ابتدا بازه زمانی را انتخاب کن.';
    } else {
      feedback.textContent = `بازه ${selected.dataset.slot} انتخاب شد. ثبت نهایی نیاز به اتصال Django دارد.`;
    }
  });
}

function initTracking() {
  const drawer = document.getElementById('mobile-drawer');
  const backdrop = document.getElementById('drawer-backdrop');
  const openButton = document.getElementById('drawer-open-btn');
  const closeButton = document.getElementById('drawer-close-btn');
  openButton.setAttribute('aria-expanded', 'false');
  drawer.inert = true;

  function toggleDrawer(open) {
    drawer.inert = !open;
    drawer.classList.toggle('translate-x-full', !open);
    backdrop.classList.toggle('hidden', !open);
    backdrop.classList.toggle('opacity-0', !open);
    openButton.setAttribute('aria-expanded', String(open));
    (open ? closeButton : openButton).focus();
  }

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && !drawer.inert) toggleDrawer(false);
  });

  // متغیرهای حالت تعاملی جهت شبیه‌سازی UI
  let currentState = 'confirmed';

  function switchState(state) {
    currentState = state;

    // به‌روزرسانی استایل دکمه‌های کنترل
    document.querySelectorAll('.state-btn').forEach(btn => {
      if (btn.getAttribute('data-state') === state) {
        btn.classList.add('bg-primary', 'text-on-primary');
        btn.classList.remove('bg-surface-container-lowest', 'text-on-surface');
      } else {
        btn.classList.remove('bg-primary', 'text-on-primary');
        btn.classList.add('bg-surface-container-lowest', 'text-on-surface');
      }
    });

    // مدیریت نمایش کانتینرها
    const activeView = document.getElementById('view-active-appointment');
    const cancelledView = document.getElementById('view-cancelled');
    const notFoundView = document.getElementById('view-not-found');
    const errorView = document.getElementById('view-error');

    activeView.classList.add('hidden');
    cancelledView.classList.add('hidden');
    notFoundView.classList.add('hidden');
    errorView.classList.add('hidden');

    if (state === 'cancelled') {
      cancelledView.classList.remove('hidden');
      return;
    }

    if (state === 'not_found') {
      notFoundView.classList.remove('hidden');
      return;
    }

    if (state === 'error') {
      errorView.classList.remove('hidden');
      return;
    }

    // حالت‌های نوبت فعال (گام ۱، ۲، ۳)
    activeView.classList.remove('hidden');

    const statusBanner = document.getElementById('status-banner');
    const statusIcon = document.getElementById('status-icon');
    const statusText = document.getElementById('status-text');
    const badgePill = document.getElementById('badge-pill');

    const step2Icon = document.getElementById('step-2-icon');
    const step2Title = document.getElementById('step-2-title');
    const step2Badge = document.getElementById('step-2-badge');
    const step2Desc = document.getElementById('step-2-desc');

    const step3Icon = document.getElementById('step-3-icon');
    const step3Title = document.getElementById('step-3-title');
    const step3Badge = document.getElementById('step-3-badge');
    const step3Desc = document.getElementById('step-3-desc');

    if (state === 'confirmed') {
      // گام ۱ فعال، ۲ و ۳ معلق
      statusBanner.className = 'px-space-md py-2.5 bg-primary/10 flex items-center justify-between';
      statusIcon.textContent = 'verified';
      statusIcon.className = 'material-symbols-outlined text-primary text-[20px]';
      statusText.textContent = 'نوبت رزرو شده و معتبر است';
      statusText.className = 'font-label-md text-label-md text-primary font-bold';
      badgePill.textContent = 'مرحله ۱ از ۳';
      badgePill.className = 'bg-primary text-on-primary font-label-sm text-label-sm px-2.5 py-0.5 rounded-full shadow-sm';

      // مرحله ۲ خنثی
      step2Icon.className = 'w-10 h-10 rounded-full bg-surface-container text-outline flex items-center justify-center shrink-0 shadow-sm';
      step2Icon.innerHTML = `<span class="material-symbols-outlined text-[20px]">how_to_reg</span>`;
      step2Title.className = 'font-label-lg text-label-lg font-semibold text-outline';
      step2Badge.className = 'font-label-sm text-label-sm text-outline';
      step2Badge.textContent = 'در انتظار مراجعه';

      // مرحله ۳ خنثی
      step3Icon.className = 'w-10 h-10 rounded-full bg-surface-container text-outline flex items-center justify-center shrink-0 shadow-sm';
      step3Icon.innerHTML = `<span class="material-symbols-outlined text-[20px]">volunteer_activism</span>`;
      step3Title.className = 'font-label-lg text-label-lg font-semibold text-outline';
      step3Badge.className = 'font-label-sm text-label-sm text-outline';
      step3Badge.textContent = 'مرحله نهایی';
    } 
    else if (state === 'checked_in') {
      // گام ۲ تکمیل‌شده، اعلام حضور در پایگاه
      statusBanner.className = 'px-space-md py-2.5 bg-secondary/15 flex items-center justify-between';
      statusIcon.textContent = 'check_circle';
      statusIcon.className = 'material-symbols-outlined text-secondary text-[20px]';
      statusText.textContent = 'مراجعه حضوری به پایگاه ثبت شد';
      statusText.className = 'font-label-md text-label-md text-secondary font-bold';
      badgePill.textContent = 'مرحله ۲ از ۳';
      badgePill.className = 'bg-secondary text-on-secondary font-label-sm text-label-sm px-2.5 py-0.5 rounded-full shadow-sm';

      // مرحله ۲ سبز
      step2Icon.className = 'w-10 h-10 rounded-full bg-secondary text-on-secondary flex items-center justify-center shrink-0 shadow-sm';
      step2Icon.innerHTML = `<span class="material-symbols-outlined text-[20px]" style="font-variation-settings: 'FILL' 1;">check_circle</span>`;
      step2Title.className = 'font-label-lg text-label-lg font-bold text-on-surface';
      step2Badge.className = 'font-label-sm text-label-sm text-secondary font-semibold';
      step2Badge.textContent = 'انجام شد (۱۰:۰۵)';

      // مرحله ۳ جاری (زرشکی)
      step3Icon.className = 'w-10 h-10 rounded-full bg-primary text-on-primary flex items-center justify-center shrink-0 shadow-sm ring-4 ring-primary/20 animate-pulse';
      step3Icon.innerHTML = `<span class="material-symbols-outlined text-[20px]">vital_signs</span>`;
      step3Title.className = 'font-label-lg text-label-lg font-bold text-primary';
      step3Badge.className = 'font-label-sm text-label-sm text-primary font-bold';
      step3Badge.textContent = 'در حال انجام خون‌گیری';
    } 
    else if (state === 'completed') {
      // گام ۳ کامل، اهدا با موفقیت پایان یافته
      statusBanner.className = 'px-space-md py-2.5 bg-secondary-container flex items-center justify-between';
      statusIcon.textContent = 'favorite';
      statusIcon.className = 'material-symbols-outlined text-on-secondary-container text-[20px]';
      statusText.textContent = 'اهدای خون با موفقیت انجام شد • سپاس از ایثار شما';
      statusText.className = 'font-label-md text-label-md text-on-secondary-container font-bold';
      badgePill.textContent = 'فرآیند تکمیل شد';
      badgePill.className = 'bg-secondary text-on-secondary font-label-sm text-label-sm px-2.5 py-0.5 rounded-full shadow-sm';

      // مرحله ۲ سبز
      step2Icon.className = 'w-10 h-10 rounded-full bg-secondary text-on-secondary flex items-center justify-center shrink-0 shadow-sm';
      step2Icon.innerHTML = `<span class="material-symbols-outlined text-[20px]" style="font-variation-settings: 'FILL' 1;">check_circle</span>`;
      step2Title.className = 'font-label-lg text-label-lg font-bold text-on-surface';
      step2Badge.className = 'font-label-sm text-label-sm text-secondary font-semibold';
      step2Badge.textContent = 'انجام شد';

      // مرحله ۳ سبز کامل
      step3Icon.className = 'w-10 h-10 rounded-full bg-secondary text-on-secondary flex items-center justify-center shrink-0 shadow-sm';
      step3Icon.innerHTML = `<span class="material-symbols-outlined text-[20px]" style="font-variation-settings: 'FILL' 1;">favorite</span>`;
      step3Title.className = 'font-label-lg text-label-lg font-bold text-on-surface';
      step3Badge.className = 'font-label-sm text-label-sm text-secondary font-semibold';
      step3Badge.textContent = 'ثبت نهایی شد';
    }
  }

  function copyTrackingCode(code) {
    if (navigator.clipboard) {
      navigator.clipboard.writeText(code).then(() => {
        const btnText = document.getElementById('copy-btn-text');
        btnText.textContent = 'کپی شد!';
        setTimeout(() => {
          btnText.textContent = 'کپی کد';
        }, 2200);
      });
    }
  }

  function clearInput() {
    const input = document.getElementById('tracking-input');
    input.value = '';
    input.focus();
  }

  function resetTrackingInput() {
    const input = document.getElementById('tracking-input');
    input.value = 'BLD-1403-8721';
    switchState('confirmed');
  }

  function handleSearch(event) {
    event.preventDefault();
    const query = document.getElementById('tracking-input').value.trim();
    if (!query) return;

    if (query.includes('000') || query.length < 5) {
      switchState('not_found');
    } else if (query.includes('err')) {
      switchState('error');
    } else {
      switchState('confirmed');
    }
  }

  function simulateRetry() {
    const btn = document.getElementById('retry-btn');
    const label = document.getElementById('retry-label');
    const icon = document.getElementById('retry-icon');

    label.textContent = 'در حال اتصال به سرور دانشگاه...';
    icon.classList.add('animate-spin');

    setTimeout(() => {
      icon.classList.remove('animate-spin');
      label.textContent = 'تلاش مجدد برای استعلام';
      switchState('confirmed');
    }, 1200);
  }

  function showCampusMapAlert() {
    alert('پایگاه خون‌گیری: پردیس کمالوند، جنب درب غربی، ساختمان سالن ورزشی امام علی (ع). تابلوهای راهنمای BloodNet در سرتاسر مسیر نصب شده‌اند.');
  }

  function confirmCancelPrompt() {
    if (confirm('آیا از درخواست لغو نوبت شماره BLD-1403-8721 اطمینان دارید؟ با لغو، ظرفیت آزاد خواهد شد.')) {
      switchState('cancelled');
    }
  }

  document.querySelector('[data-action="tracking-1"]')
    .addEventListener("click", (event) => {
      toggleDrawer(true);
    });

  document.querySelector('[data-action="tracking-2"]')
    .addEventListener("click", (event) => {
      toggleDrawer(false);
    });

  document.querySelector('[data-action="tracking-3"]')
    .addEventListener("click", (event) => {
      toggleDrawer(false);
    });

  document.querySelector('[data-action="tracking-4"]')
    .addEventListener("click", (event) => {
      switchState('confirmed');
    });

  document.querySelector('[data-action="tracking-5"]')
    .addEventListener("click", (event) => {
      switchState('checked_in');
    });

  document.querySelector('[data-action="tracking-6"]')
    .addEventListener("click", (event) => {
      switchState('completed');
    });

  document.querySelector('[data-action="tracking-7"]')
    .addEventListener("click", (event) => {
      switchState('cancelled');
    });

  document.querySelector('[data-action="tracking-8"]')
    .addEventListener("click", (event) => {
      switchState('not_found');
    });

  document.querySelector('[data-action="tracking-9"]')
    .addEventListener("click", (event) => {
      switchState('error');
    });

  document.querySelector('[data-action="tracking-10"]')
    .addEventListener("submit", (event) => {
      handleSearch(event);
    });

  document.querySelector('[data-action="tracking-11"]')
    .addEventListener("click", (event) => {
      clearInput();
    });

  document.querySelector('[data-action="tracking-12"]')
    .addEventListener("click", (event) => {
      copyTrackingCode('BLD-1403-8721');
    });

  document.querySelector('[data-action="tracking-13"]')
    .addEventListener("click", (event) => {
      showCampusMapAlert();
    });

  document.querySelector('[data-action="tracking-14"]')
    .addEventListener("click", (event) => {
      confirmCancelPrompt();
    });

  document.querySelector('[data-action="tracking-15"]')
    .addEventListener("click", (event) => {
      switchState('confirmed');
    });

  document.querySelector('[data-action="tracking-16"]')
    .addEventListener("click", (event) => {
      resetTrackingInput();
    });

  document.querySelector('[data-action="tracking-17"]')
    .addEventListener("click", (event) => {
      simulateRetry();
    });
}

function initInvitation() {
  function openDrawer() {
    const drawer = document.getElementById('mobile-drawer');
    const overlay = document.getElementById('mobile-drawer-overlay');
    if (drawer && overlay) {
      overlay.classList.remove('opacity-0', 'pointer-events-none');
      overlay.classList.add('opacity-100', 'pointer-events-auto');
      drawer.classList.remove('translate-x-full');
      drawer.classList.add('translate-x-0');
      document.getElementById('drawer-close-btn')?.focus();
    }
  }

  function closeDrawer() {
    const drawer = document.getElementById('mobile-drawer');
    const overlay = document.getElementById('mobile-drawer-overlay');
    if (drawer && overlay) {
      overlay.classList.remove('opacity-100', 'pointer-events-auto');
      overlay.classList.add('opacity-0', 'pointer-events-none');
      drawer.classList.remove('translate-x-0');
      drawer.classList.add('translate-x-full');
      document.getElementById('drawer-toggle-btn')?.focus();
    }
  }

  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') {
      closeDrawer();
    }
  });

  function switchState(stateName) {
    const states = ['active', 'accepted', 'declined', 'expired'];
    states.forEach(st => {
      const view = document.getElementById('view-' + st);
      const tab = document.getElementById('tab-' + st);
      if (view) {
        if (st === stateName) {
          view.classList.remove('hidden');
          view.classList.add('flex');
        } else {
          view.classList.remove('flex');
          view.classList.add('hidden');
        }
      }
      if (tab) {
        if (st === stateName) {
          tab.classList.add('bg-surface-container-lowest', 'text-primary', 'shadow-xs', 'font-bold');
          tab.classList.remove('text-on-surface-variant');
        } else {
          tab.classList.remove('bg-surface-container-lowest', 'text-primary', 'shadow-xs', 'font-bold');
          tab.classList.add('text-on-surface-variant');
        }
      }
    });
  }

  function handleAcceptClick(e) {
    // If user clicks in preview test mode without wanting instant navigate, can toggle feedback
  }

  function handleDecline() {
    switchState('declined');
  }

  document.querySelector('[data-action="invitation-1"]')
    .addEventListener("click", (event) => {
      openDrawer();
    });

  document.querySelector('[data-action="invitation-2"]')
    .addEventListener("click", (event) => {
      closeDrawer();
    });

  document.querySelector('[data-action="invitation-3"]')
    .addEventListener("click", (event) => {
      closeDrawer();
    });

  document.querySelector('[data-action="invitation-4"]')
    .addEventListener("click", (event) => {
      switchState('active');
    });

  document.querySelector('[data-action="invitation-5"]')
    .addEventListener("click", (event) => {
      switchState('accepted');
    });

  document.querySelector('[data-action="invitation-6"]')
    .addEventListener("click", (event) => {
      switchState('declined');
    });

  document.querySelector('[data-action="invitation-7"]')
    .addEventListener("click", (event) => {
      switchState('expired');
    });

  document.querySelector('[data-action="invitation-8"]')
    .addEventListener("click", (event) => {
      handleAcceptClick(event);
    });

  document.querySelector('[data-action="invitation-9"]')
    .addEventListener("click", (event) => {
      handleDecline();
    });

  document.querySelector('[data-action="invitation-10"]')
    .addEventListener("click", (event) => {
      switchState('active');
    });

  document.querySelector('[data-action="invitation-11"]')
    .addEventListener("click", (event) => {
      switchState('active');
    });

  document.querySelector('[data-action="invitation-12"]')
    .addEventListener("click", (event) => {
      switchState('active');
    });
}

const pages = {
  home: { title: 'اهدای خون در دانشگاه لرستان', init: initHome },
  registration: { title: 'ثبت‌نام اهدای خون', init: initRegistration },
  tracking: { title: 'پیگیری نوبت', init: initTracking },
  invitation: { title: 'دعوت‌نامه اهدای خون', init: initInvitation },
};
const requestedPage = new URLSearchParams(window.location.search).get('page');
const page = Object.hasOwn(pages, requestedPage) ? requestedPage : 'home';
const template = document.getElementById(`page-${page}`);

document.title = pages[page].title;
document.body.dataset.page = page;
document.body.append(template.content.cloneNode(true));
pages[page].init();
