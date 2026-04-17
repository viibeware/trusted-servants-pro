// SPDX-License-Identifier: AGPL-3.0-or-later
// First-run guided tour for Trusted Servants Pro.
// Auto-starts on the dashboard for non-admin users missing the
// `tsp-tour-seen` cookie. Also exposes window.tspTour.start() so
// anyone can replay it from the Help modal.

(function () {
  "use strict";

  const COOKIE_NAME = "tsp-tour-seen";

  const STEPS = [
    {
      title: "Welcome to Trusted Servants Pro",
      content: "This is your group's portal for meetings, readings, files, and Zoom hosting. Let's take a 60-second tour.",
      position: "center",
    },
    {
      target: '.sidebar nav a[href="/"]',
      title: "Dashboard",
      content: "Your home view. Shows your role, what you can do, and recent activity across the portal.",
      position: "right",
    },
    {
      target: '.sidebar nav a[href="/meetings"]',
      title: "Meetings",
      content: "Every meeting your group runs — schedules, Zoom info, and attached readings. Open any meeting for full details.",
      position: "right",
    },
    {
      target: '.sidebar nav a[href="/libraries"]',
      title: "Libraries",
      content: "Curated reading collections that get attached to meetings. Browse files, body text, and thumbnails.",
      position: "right",
    },
    {
      target: '.sidebar nav a[href="/files"]',
      title: "File Browser",
      content: "The central library of every uploaded file. Click an image or PDF to preview it in place, or copy a shareable link.",
      position: "right",
    },
    {
      target: '.sidebar nav a[href="/zoom-accounts"]',
      title: "Zoom Accounts",
      content: "Shared Zoom host credentials and a weekly calendar showing who's hosting when, color-coded by assignment.",
      position: "right",
    },
    {
      target: '[data-open-modal="settings-modal"]',
      title: "Your Settings",
      content: "Click the gear icon to change your theme, view the About page, and manage your preferences.",
      position: "right",
    },
    {
      target: '[data-open-modal="pic-help-modal"]',
      title: "Need help?",
      content: "The Help button opens contact info for your group's Public Information Chair — and it's where you can replay this tour anytime.",
      position: "right",
    },
    {
      title: "You're all set",
      content: "Explore the portal at your own pace. Replay this tour anytime from the Help (?) button in the sidebar.",
      position: "center",
    },
  ];

  function getCookie(name) {
    const re = new RegExp("(?:^|;\\s*)" + name + "=([^;]*)");
    const m = document.cookie.match(re);
    return m ? decodeURIComponent(m[1]) : null;
  }

  function setCookie(name, value) {
    const expires = new Date();
    expires.setFullYear(expires.getFullYear() + 5);
    document.cookie = name + "=" + encodeURIComponent(value) +
      "; expires=" + expires.toUTCString() + "; path=/; SameSite=Lax";
  }

  function Tour(steps) {
    this.steps = steps;
    this.i = 0;
    this.mobileDrawerOpened = false;
  }

  Tour.prototype.start = function () {
    if (this.overlay) return; // already running
    this.build();
    this.show(0);
  };

  Tour.prototype.build = function () {
    const el = document.createElement("div");
    el.className = "tour-overlay";
    el.innerHTML =
      '<div class="tour-hole" hidden></div>' +
      '<div class="tour-card" role="dialog" aria-modal="true" aria-labelledby="tour-title">' +
        '<div class="tour-card-head">' +
          '<div class="tour-step-count"></div>' +
          '<button type="button" class="tour-close" aria-label="Close tour">&times;</button>' +
        '</div>' +
        '<h3 class="tour-title" id="tour-title"></h3>' +
        '<p class="tour-content"></p>' +
        '<div class="tour-progress" aria-hidden="true"></div>' +
        '<div class="tour-actions">' +
          '<button type="button" class="btn tour-prev">Back</button>' +
          '<button type="button" class="btn tour-skip">Skip</button>' +
          '<button type="button" class="btn btn-primary tour-next">Next</button>' +
        '</div>' +
      '</div>';
    document.body.appendChild(el);
    this.overlay = el;
    this.hole = el.querySelector(".tour-hole");
    this.card = el.querySelector(".tour-card");
    this.titleEl = el.querySelector(".tour-title");
    this.contentEl = el.querySelector(".tour-content");
    this.countEl = el.querySelector(".tour-step-count");
    this.progressEl = el.querySelector(".tour-progress");
    this.prevBtn = el.querySelector(".tour-prev");
    this.nextBtn = el.querySelector(".tour-next");
    this.skipBtn = el.querySelector(".tour-skip");
    this.closeBtn = el.querySelector(".tour-close");

    // Progress dots
    for (let j = 0; j < this.steps.length; j++) {
      const d = document.createElement("span");
      d.className = "tour-dot";
      this.progressEl.appendChild(d);
    }

    const self = this;
    this.prevBtn.addEventListener("click", function () { self.show(self.i - 1); });
    this.nextBtn.addEventListener("click", function () {
      if (self.i < self.steps.length - 1) self.show(self.i + 1);
      else self.finish();
    });
    this.skipBtn.addEventListener("click", function () { self.finish(); });
    this.closeBtn.addEventListener("click", function () { self.finish(); });

    this.keyHandler = function (e) {
      if (e.key === "Escape") self.finish();
      else if (e.key === "ArrowRight" || e.key === "Enter") self.nextBtn.click();
      else if (e.key === "ArrowLeft") self.prevBtn.click();
    };
    document.addEventListener("keydown", this.keyHandler);

    this.resizeHandler = function () { self.show(self.i); };
    window.addEventListener("resize", this.resizeHandler);
  };

  Tour.prototype.show = function (i) {
    if (i < 0 || i >= this.steps.length) return;
    this.i = i;
    const step = this.steps[i];
    this.titleEl.textContent = step.title;
    this.contentEl.textContent = step.content;
    this.countEl.textContent = (i + 1) + " of " + this.steps.length;
    this.prevBtn.disabled = (i === 0);
    this.nextBtn.textContent = (i === this.steps.length - 1) ? "Finish" : "Next";

    const dots = this.progressEl.querySelectorAll(".tour-dot");
    dots.forEach(function (d, j) {
      d.classList.toggle("active", j === i);
      d.classList.toggle("done", j < i);
    });

    // Mobile: ensure sidebar drawer is open if the step targets a sidebar link
    if (step.target && step.target.indexOf(".sidebar") === 0) {
      this.ensureSidebarOpen();
    }

    const target = step.target ? document.querySelector(step.target) : null;
    if (target && target.offsetParent !== null) {
      const rect = target.getBoundingClientRect();
      this.positionHole(rect);
      this.positionCard(rect, step.position || "right");
    } else {
      this.hole.hidden = true;
      this.centerCard();
    }
  };

  Tour.prototype.ensureSidebarOpen = function () {
    const side = document.querySelector(".sidebar");
    if (side && window.innerWidth <= 900 && !side.classList.contains("open")) {
      side.classList.add("open");
      this.mobileDrawerOpened = true;
    }
  };

  Tour.prototype.positionHole = function (rect) {
    const pad = 6;
    this.hole.hidden = false;
    this.hole.style.left = (rect.left - pad) + "px";
    this.hole.style.top = (rect.top - pad) + "px";
    this.hole.style.width = (rect.width + pad * 2) + "px";
    this.hole.style.height = (rect.height + pad * 2) + "px";
  };

  Tour.prototype.positionCard = function (rect, position) {
    const pad = 20;
    const cardW = Math.min(360, window.innerWidth - 32);
    const cardH = this.card.offsetHeight || 220;
    this.card.style.width = cardW + "px";
    let left, top;
    switch (position) {
      case "right":
        left = rect.right + pad;
        top = rect.top + rect.height / 2 - cardH / 2;
        break;
      case "left":
        left = rect.left - cardW - pad;
        top = rect.top + rect.height / 2 - cardH / 2;
        break;
      case "top":
        left = rect.left + rect.width / 2 - cardW / 2;
        top = rect.top - cardH - pad;
        break;
      case "bottom":
        left = rect.left + rect.width / 2 - cardW / 2;
        top = rect.bottom + pad;
        break;
      default:
        this.centerCard();
        return;
    }
    // If the preferred side overflows the viewport, flip or clamp.
    if (left + cardW > window.innerWidth - 12) left = window.innerWidth - cardW - 12;
    if (left < 12) left = 12;
    if (top + cardH > window.innerHeight - 12) top = window.innerHeight - cardH - 12;
    if (top < 12) top = 12;
    this.card.style.left = left + "px";
    this.card.style.top = top + "px";
    this.card.style.transform = "none";
  };

  Tour.prototype.centerCard = function () {
    this.card.style.width = Math.min(420, window.innerWidth - 32) + "px";
    this.card.style.left = "50%";
    this.card.style.top = "50%";
    this.card.style.transform = "translate(-50%, -50%)";
  };

  Tour.prototype.finish = function () {
    setCookie(COOKIE_NAME, "1");
    this.teardown();
  };

  Tour.prototype.teardown = function () {
    if (!this.overlay) return;
    if (this.mobileDrawerOpened) {
      const side = document.querySelector(".sidebar");
      if (side) side.classList.remove("open");
      this.mobileDrawerOpened = false;
    }
    document.removeEventListener("keydown", this.keyHandler);
    window.removeEventListener("resize", this.resizeHandler);
    this.overlay.remove();
    this.overlay = null;
  };

  function shouldAutoStart() {
    if (getCookie(COOKIE_NAME)) return false;
    // Only auto-start on the dashboard.
    if (window.location.pathname !== "/") return false;
    // Skip for admins (they have the setup wizard).
    const role = (window.tspUser && window.tspUser.role) || "";
    if (role === "admin") return false;
    return true;
  }

  const tour = new Tour(STEPS);
  window.tspTour = {
    start: function () { tour.i = 0; tour.mobileDrawerOpened = false; tour.start(); },
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", maybeAutoStart);
  } else {
    maybeAutoStart();
  }
  function maybeAutoStart() {
    if (!shouldAutoStart()) return;
    // Small delay so the page has rendered and transitions are settled.
    setTimeout(function () { window.tspTour.start(); }, 400);
  }
})();
