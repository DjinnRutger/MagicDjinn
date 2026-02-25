/**
 * LocalVibe – Sidebar & UI JavaScript
 */

(function () {
  "use strict";

  /* ── Theme: apply before first paint (no FOUC) ───────────────────────────── */
  (function () {
    var t = localStorage.getItem("theme");
    // Migrate old darkMode key
    if (!t) { var old = localStorage.getItem("darkMode"); if (old === "true") t = "dark"; }
    var pref = document.documentElement.dataset.userTheme || "light";
    var theme = t || pref;
    document.documentElement.setAttribute("data-theme", theme);
    document.documentElement.setAttribute("data-bs-theme", theme === "light" ? "light" : "dark");
  })();

  /* ── Apply theme and persist ─────────────────────────────────────────────── */
  window.applyTheme = function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    document.documentElement.setAttribute("data-bs-theme", theme === "light" ? "light" : "dark");
    localStorage.setItem("theme", theme);
    // Mark active button
    document.querySelectorAll(".theme-btn").forEach(function (btn) {
      btn.classList.toggle("active", btn.dataset.themeVal === theme);
    });
    // Persist to server (best-effort)
    fetch("/api/set-theme", {
      method: "POST",
      headers: {
        "X-CSRFToken": getCSRFToken(),
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ theme: theme }),
    }).catch(function () {/* silently ignore network errors */});
  }

  document.addEventListener("DOMContentLoaded", function () {

    /* ── Sidebar toggle (desktop collapse / mobile slide) ─────────────────── */
    const sidebarToggleBtn = document.getElementById("sidebar-toggle");
    const sidebar          = document.getElementById("sidebar");
    const overlay          = document.getElementById("sidebar-overlay");
    const body             = document.body;

    function isMobile() {
      return window.innerWidth < 992;
    }

    if (sidebarToggleBtn) {
      sidebarToggleBtn.addEventListener("click", function () {
        if (isMobile()) {
          body.classList.toggle("sidebar-open");
        } else {
          body.classList.toggle("sidebar-collapsed");
          localStorage.setItem("sidebarCollapsed", body.classList.contains("sidebar-collapsed"));
        }
      });
    }

    // Close sidebar when overlay is clicked (mobile)
    if (overlay) {
      overlay.addEventListener("click", function () {
        body.classList.remove("sidebar-open");
      });
    }

    // Restore desktop collapsed state from localStorage
    if (!isMobile() && localStorage.getItem("sidebarCollapsed") === "true") {
      body.classList.add("sidebar-collapsed");
    }

    // Close mobile sidebar on window resize to desktop
    window.addEventListener("resize", function () {
      if (!isMobile()) {
        body.classList.remove("sidebar-open");
      }
    });

    /* ── Theme picker buttons ─────────────────────────────────────────────── */
    const currentTheme = document.documentElement.getAttribute("data-theme") || "light";
    document.querySelectorAll(".theme-btn").forEach(function (btn) {
      // Mark the currently active theme
      if (btn.dataset.themeVal === currentTheme) btn.classList.add("active");
      btn.addEventListener("click", function () {
        applyTheme(btn.dataset.themeVal);
      });
    });

    /* ── Auto-dismiss flash messages after 5 s ───────────────────────────── */
    document.querySelectorAll(".flash-messages .alert").forEach(function (el) {
      setTimeout(function () {
        const bsAlert = bootstrap.Alert.getOrCreateInstance(el);
        if (bsAlert) bsAlert.close();
      }, 5000);
    });

    /* ── Confirm dangerous actions ───────────────────────────────────────── */
    document.querySelectorAll("[data-confirm]").forEach(function (el) {
      el.addEventListener("click", function (e) {
        const msg = el.dataset.confirm || "Are you sure?";
        if (!confirm(msg)) {
          e.preventDefault();
          e.stopImmediatePropagation();
        }
      });
    });

    /* ── Submit delete/toggle forms via confirm button ───────────────────── */
    document.querySelectorAll("form[data-confirm]").forEach(function (form) {
      form.addEventListener("submit", function (e) {
        const msg = form.dataset.confirm || "Are you sure?";
        if (!confirm(msg)) {
          e.preventDefault();
        }
      });
    });

    /* ── Permission checkbox highlighting ────────────────────────────────── */
    document.querySelectorAll(".permission-item input[type='checkbox']").forEach(function (cb) {
      function update() {
        cb.closest(".permission-item").classList.toggle("checked", cb.checked);
      }
      update();
      cb.addEventListener("change", update);
    });

    /* ── Settings: highlight changed rows ───────────────────────────────── */
    document.querySelectorAll(".settings-row input, .settings-row select, .settings-row textarea").forEach(function (el) {
      const row = el.closest(".settings-row");
      const original = el.type === "checkbox" ? el.checked : el.value;
      el.addEventListener("input", function () {
        const changed = el.type === "checkbox" ? el.checked !== original : el.value !== original;
        row && row.classList.toggle("table-warning", changed);
      });
    });

  }); // DOMContentLoaded

  /* ── Helper: read CSRF token from cookie or meta tag ─────────────────── */
  function getCSRFToken() {
    // Try meta tag first (most reliable with Flask-WTF)
    const meta = document.querySelector('meta[name="csrf-token"]');
    if (meta) return meta.getAttribute("content");
    // Fall back to cookie
    const match = document.cookie.match(/csrf_token=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : "";
  }

})();
