/**
 * styled-dropdown.js — PrepWithTee Premium Dropdown Component
 *
 * Usage:
 *   const sd = new StyledDropdown(selectElement, options?)
 *
 * Options:
 *   grouped    {bool}   – render <optgroup> labels as non-clickable section headers
 *   searchable {bool}   – show filter input (auto-enabled when options > 8)
 *   placeholder {string} – text shown when no option selected
 *
 * Public API:
 *   sd.refresh()  – repopulate from underlying <select> (call after DOM changes)
 *   sd.destroy()  – restore native <select>, remove custom widget
 *   sd.setValue(val) – set value programmatically and fire change event
 *
 * The underlying <select> stays in the DOM (visibility:hidden) and stays in
 * sync — all existing .value reads and 'change' listeners keep working.
 */

(function () {
  "use strict";

  // ── Inject styles once ────────────────────────────────────────────────────
  const STYLE_ID = "styled-dropdown-styles";
  if (!document.getElementById(STYLE_ID)) {
    const style = document.createElement("style");
    style.id = STYLE_ID;
    style.textContent = `
/* ── StyledDropdown ──────────────────────────────────────────────────── */
.sd-wrapper {
  position: relative;
  display: inline-block;
  width: 100%;
  font-family: "Hanken Grotesk", system-ui, sans-serif;
}

/* Trigger button */
.sd-trigger {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  width: 100%;
  padding: 9px 12px;
  background: var(--white, #fff);
  color: var(--ink, #1A1A2E);
  border: 1.5px solid var(--line, #E8DFCE);
  border-radius: 10px;
  font: 500 0.87rem "Hanken Grotesk", system-ui, sans-serif;
  cursor: pointer;
  text-align: left;
  transition: border-color 0.15s, box-shadow 0.15s;
  user-select: none;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  min-height: 38px;
}
.sd-trigger:hover {
  border-color: var(--gold, #E8913A);
}
.sd-trigger:focus-visible {
  outline: none;
  border-color: var(--purple-bright, #6B3FA0);
  box-shadow: 0 0 0 3px rgba(107, 63, 160, 0.12);
}
.sd-trigger.sd-open {
  border-color: var(--gold, #E8913A);
  border-bottom-left-radius: 6px;
  border-bottom-right-radius: 6px;
}
.sd-trigger-label {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sd-trigger-label.sd-placeholder {
  color: var(--grey, #5A5A72);
  opacity: 0.8;
}
.sd-chevron {
  flex-shrink: 0;
  color: var(--grey, #5A5A72);
  transition: transform 0.2s ease;
}
.sd-trigger.sd-open .sd-chevron {
  transform: rotate(180deg);
  color: var(--gold, #E8913A);
}

/* Dropdown panel */
.sd-panel {
  position: absolute;
  top: calc(100% - 2px);
  left: 0;
  right: 0;
  z-index: 9999;
  background: var(--white, #fff);
  border: 1.5px solid var(--gold, #E8913A);
  border-top: none;
  border-bottom-left-radius: 10px;
  border-bottom-right-radius: 10px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.14);
  max-height: 280px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  animation: sd-open 0.12s ease;
}
@keyframes sd-open {
  from { opacity: 0; transform: translateY(-4px); }
  to   { opacity: 1; transform: translateY(0); }
}

/* Search box */
.sd-search-wrap {
  padding: 8px 10px 6px;
  border-bottom: 1px solid var(--line, #E8DFCE);
  flex-shrink: 0;
}
.sd-search {
  width: 100%;
  padding: 6px 10px 6px 28px;
  border: 1.5px solid var(--line, #E8DFCE);
  border-radius: 7px;
  background: var(--page, #FDF9F3);
  color: var(--ink, #1A1A2E);
  font: 500 0.82rem "Hanken Grotesk", system-ui, sans-serif;
  outline: none;
  transition: border-color 0.15s;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='13' height='13' viewBox='0 0 24 24' fill='none' stroke='%235A5A72' stroke-width='2.5' stroke-linecap='round' stroke-linejoin='round'%3E%3Ccircle cx='11' cy='11' r='8'/%3E%3Cpath d='m21 21-4.35-4.35'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: 8px center;
}
.sd-search:focus {
  border-color: var(--gold, #E8913A);
}

/* Options list */
.sd-list {
  overflow-y: auto;
  flex: 1;
  padding: 4px 0;
  scrollbar-width: thin;
  scrollbar-color: var(--line, #E8DFCE) transparent;
}
.sd-list::-webkit-scrollbar { width: 5px; }
.sd-list::-webkit-scrollbar-track { background: transparent; }
.sd-list::-webkit-scrollbar-thumb { background: var(--line, #E8DFCE); border-radius: 10px; }

/* Group header */
.sd-group-header {
  padding: 8px 12px 4px;
  font-size: 0.68rem;
  font-weight: 800;
  letter-spacing: 0.07em;
  text-transform: uppercase;
  color: var(--grey, #5A5A72);
  border-left: 2.5px solid var(--gold, #E8913A);
  margin: 4px 6px 0;
  line-height: 1;
  user-select: none;
}

/* Option item */
.sd-option {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  margin: 1px 4px;
  border-radius: 7px;
  font: 500 0.85rem "Hanken Grotesk", system-ui, sans-serif;
  color: var(--ink, #1A1A2E);
  cursor: pointer;
  transition: background 0.1s;
  user-select: none;
}
.sd-option:hover,
.sd-option.sd-focused {
  background: var(--lav, #E4DEF9);
  color: var(--lav-ink, #4A2E8F);
}
.sd-option.sd-selected {
  color: var(--purple-bright, #6B3FA0);
  font-weight: 700;
}
.sd-option.sd-selected::after {
  content: "✓";
  margin-left: auto;
  color: var(--gold, #E8913A);
  font-size: 0.9rem;
  font-weight: 900;
  flex-shrink: 0;
}
.sd-option[aria-disabled="true"] {
  display: none; /* filtered out options */
}

/* Empty state */
.sd-empty {
  padding: 16px 12px;
  text-align: center;
  font-size: 0.82rem;
  color: var(--grey, #5A5A72);
}

/* Hide original select without removing from DOM */
.sd-hidden-select {
  position: absolute;
  opacity: 0;
  pointer-events: none;
  height: 0;
  width: 0;
  overflow: hidden;
}
/* ── /StyledDropdown ─────────────────────────────────────────────────── */
    `;
    document.head.appendChild(style);
  }

  // ── StyledDropdown class ─────────────────────────────────────────────────
  class StyledDropdown {
    /**
     * @param {HTMLSelectElement} selectEl  The native select to enhance
     * @param {object} [opts]
     * @param {boolean} [opts.grouped=false]     – use optgroup labels as section headers
     * @param {boolean} [opts.searchable]        – show search box (auto if options > 8)
     * @param {string}  [opts.placeholder]       – placeholder text
     */
    constructor(selectEl, opts = {}) {
      if (!selectEl || selectEl._sdInstance) return;
      selectEl._sdInstance = this;
      this._select = selectEl;
      this._opts = {
        grouped: opts.grouped ?? false,
        searchable: opts.searchable,           // undefined → auto
        placeholder: opts.placeholder ?? selectEl.dataset.placeholder ?? "Select…",
      };
      this._open = false;
      this._focused = -1;   // index into this._visibleItems
      this._visibleItems = [];

      this._build();
    }

    // ── Build wrapper ──────────────────────────────────────────────────────
    _build() {
      const sel = this._select;

      // Wrap the select
      const wrapper = document.createElement("div");
      wrapper.className = "sd-wrapper";
      wrapper.setAttribute("role", "combobox");
      wrapper.setAttribute("aria-haspopup", "listbox");
      wrapper.setAttribute("aria-expanded", "false");
      sel.parentNode.insertBefore(wrapper, sel);
      wrapper.appendChild(sel);
      sel.classList.add("sd-hidden-select");
      this._wrapper = wrapper;

      // Trigger button
      const trigger = document.createElement("button");
      trigger.type = "button";
      trigger.className = "sd-trigger";
      trigger.setAttribute("aria-expanded", "false");
      trigger.setAttribute("tabindex", "0");
      trigger.innerHTML = `
        <span class="sd-trigger-label sd-placeholder">${this._opts.placeholder}</span>
        <svg class="sd-chevron" width="12" height="12" viewBox="0 0 12 8" fill="none" aria-hidden="true">
          <path d="M1 1l5 5 5-5" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>`;
      wrapper.insertBefore(trigger, sel);
      this._trigger = trigger;
      this._label = trigger.querySelector(".sd-trigger-label");

      // Panel
      const panel = document.createElement("div");
      panel.className = "sd-panel";
      panel.style.display = "none";
      panel.setAttribute("role", "listbox");
      wrapper.appendChild(panel);
      this._panel = panel;

      // Search
      this._searchWrap = null;
      this._searchInput = null;

      // List
      const list = document.createElement("div");
      list.className = "sd-list";
      panel.appendChild(list);
      this._list = list;

      this._populate();
      this._updateTriggerLabel();
      this._wireEvents();
    }

    // ── Populate list from <select> ────────────────────────────────────────
    _populate() {
      const sel = this._select;
      const list = this._list;
      list.innerHTML = "";

      const totalOptions = sel.options.length;
      const useSearch = this._opts.searchable !== undefined
        ? this._opts.searchable
        : totalOptions > 8;

      // Add / refresh search box
      if (useSearch) {
        if (!this._searchWrap) {
          const sw = document.createElement("div");
          sw.className = "sd-search-wrap";
          const inp = document.createElement("input");
          inp.type = "text";
          inp.className = "sd-search";
          inp.placeholder = "Search…";
          inp.setAttribute("autocomplete", "off");
          inp.setAttribute("aria-label", "Filter options");
          sw.appendChild(inp);
          this._panel.insertBefore(sw, this._list);
          this._searchWrap = sw;
          this._searchInput = inp;
          inp.addEventListener("input", () => this._filter(inp.value));
          inp.addEventListener("keydown", (e) => this._onKeydown(e));
        }
      } else if (this._searchWrap) {
        this._searchWrap.remove();
        this._searchWrap = null;
        this._searchInput = null;
      }

      if (this._opts.grouped) {
        // Render using <optgroup> structure
        for (const child of sel.children) {
          if (child.tagName === "OPTGROUP") {
            const header = document.createElement("div");
            header.className = "sd-group-header";
            header.textContent = child.label;
            header.setAttribute("aria-hidden", "true");
            list.appendChild(header);
            for (const opt of child.children) {
              list.appendChild(this._makeOptionEl(opt));
            }
          } else if (child.tagName === "OPTION") {
            list.appendChild(this._makeOptionEl(child));
          }
        }
      } else {
        for (const opt of sel.options) {
          list.appendChild(this._makeOptionEl(opt));
        }
      }

      this._rebuildVisible();
    }

    _makeOptionEl(opt) {
      const el = document.createElement("div");
      el.className = "sd-option";
      el.setAttribute("role", "option");
      el.setAttribute("data-value", opt.value);
      el.textContent = opt.textContent;
      if (opt.selected) el.classList.add("sd-selected");
      if (opt.disabled) el.setAttribute("aria-disabled", "true");
      el.addEventListener("mousedown", (e) => {
        e.preventDefault();
        this._selectValue(opt.value);
      });
      el.addEventListener("mousemove", () => {
        const idx = this._visibleItems.indexOf(el);
        if (idx !== -1) this._setFocused(idx);
      });
      return el;
    }

    _rebuildVisible() {
      this._visibleItems = [...this._list.querySelectorAll(".sd-option:not([aria-disabled='true'])")];
    }

    // ── Filter (search) ────────────────────────────────────────────────────
    _filter(query) {
      const q = query.trim().toLowerCase();
      let anyVisible = false;

      this._list.querySelectorAll(".sd-option").forEach((el) => {
        const match = !q || el.textContent.toLowerCase().includes(q);
        el.setAttribute("aria-disabled", match ? "false" : "true");
        el.style.display = match ? "" : "none";
        if (match) anyVisible = true;
      });

      // Show/hide group headers
      this._list.querySelectorAll(".sd-group-header").forEach((hdr) => {
        // Check if any following sibling option is visible
        let next = hdr.nextElementSibling;
        let groupHasVisible = false;
        while (next && !next.classList.contains("sd-group-header")) {
          if (next.style.display !== "none") groupHasVisible = true;
          next = next.nextElementSibling;
        }
        hdr.style.display = groupHasVisible ? "" : "none";
      });

      // Empty state
      let emptyEl = this._list.querySelector(".sd-empty");
      if (!anyVisible) {
        if (!emptyEl) {
          emptyEl = document.createElement("div");
          emptyEl.className = "sd-empty";
          emptyEl.textContent = "No matches";
          this._list.appendChild(emptyEl);
        }
      } else if (emptyEl) {
        emptyEl.remove();
      }

      this._rebuildVisible();
      this._setFocused(0);
    }

    // ── Open / Close ───────────────────────────────────────────────────────
    _openPanel() {
      if (this._open) return;
      this._open = true;
      this._panel.style.display = "flex";
      this._trigger.classList.add("sd-open");
      this._trigger.setAttribute("aria-expanded", "true");
      this._wrapper.setAttribute("aria-expanded", "true");
      if (this._searchInput) {
        this._searchInput.value = "";
        this._filter("");
        requestAnimationFrame(() => this._searchInput.focus());
      }
      // Scroll selected into view
      const sel = this._list.querySelector(".sd-option.sd-selected");
      if (sel) sel.scrollIntoView({ block: "nearest" });
      this._setFocused(this._visibleItems.indexOf(sel ?? this._visibleItems[0]));

      // Close on outside click
      this._outsideHandler = (e) => {
        if (!this._wrapper.contains(e.target)) this._closePanel();
      };
      document.addEventListener("mousedown", this._outsideHandler, true);
      document.addEventListener("touchstart", this._outsideHandler, { passive: true, capture: true });
    }

    _closePanel() {
      if (!this._open) return;
      this._open = false;
      this._panel.style.display = "none";
      this._trigger.classList.remove("sd-open");
      this._trigger.setAttribute("aria-expanded", "false");
      this._wrapper.setAttribute("aria-expanded", "false");
      this._focused = -1;
      document.removeEventListener("mousedown", this._outsideHandler, true);
      document.removeEventListener("touchstart", this._outsideHandler, true);
    }

    // ── Selection ──────────────────────────────────────────────────────────
    _selectValue(val) {
      const sel = this._select;
      if (sel.value === val) {
        this._closePanel();
        return;
      }
      sel.value = val;
      sel.dispatchEvent(new Event("change", { bubbles: true }));
      this._updateTriggerLabel();
      this._updateSelectedClass();
      this._closePanel();
    }

    _updateTriggerLabel() {
      const sel = this._select;
      const chosen = sel.options[sel.selectedIndex];
      if (chosen && chosen.value !== "") {
        this._label.textContent = chosen.textContent;
        this._label.classList.remove("sd-placeholder");
      } else {
        this._label.textContent = this._opts.placeholder;
        this._label.classList.add("sd-placeholder");
      }
    }

    _updateSelectedClass() {
      const val = this._select.value;
      this._list.querySelectorAll(".sd-option").forEach((el) => {
        el.classList.toggle("sd-selected", el.dataset.value === val);
      });
    }

    // ── Keyboard navigation ────────────────────────────────────────────────
    _setFocused(idx) {
      this._visibleItems.forEach((el) => el.classList.remove("sd-focused"));
      if (idx < 0 || idx >= this._visibleItems.length) {
        this._focused = -1;
        return;
      }
      this._focused = idx;
      const el = this._visibleItems[idx];
      el.classList.add("sd-focused");
      el.scrollIntoView({ block: "nearest" });
    }

    _onKeydown(e) {
      if (!this._open) {
        if (e.key === "Enter" || e.key === " " || e.key === "ArrowDown") {
          e.preventDefault();
          this._openPanel();
        }
        return;
      }
      switch (e.key) {
        case "ArrowDown":
          e.preventDefault();
          this._setFocused(Math.min(this._focused + 1, this._visibleItems.length - 1));
          break;
        case "ArrowUp":
          e.preventDefault();
          this._setFocused(Math.max(this._focused - 1, 0));
          break;
        case "Enter":
          e.preventDefault();
          if (this._focused >= 0 && this._visibleItems[this._focused]) {
            this._selectValue(this._visibleItems[this._focused].dataset.value);
          }
          break;
        case "Escape":
        case "Tab":
          this._closePanel();
          break;
      }
    }

    // ── Wire events ────────────────────────────────────────────────────────
    _wireEvents() {
      this._trigger.addEventListener("click", () => {
        this._open ? this._closePanel() : this._openPanel();
      });
      this._trigger.addEventListener("keydown", (e) => this._onKeydown(e));

      // Keep in sync if native select changes externally (e.g. via .value = x)
      this._select.addEventListener("change", () => {
        this._updateTriggerLabel();
        this._updateSelectedClass();
      });
    }

    // ── Public API ─────────────────────────────────────────────────────────

    /** Re-populate panel from current <select> options (call after DOM changes) */
    refresh() {
      this._populate();
      this._updateTriggerLabel();
    }

    /** Set value programmatically and fire change event */
    setValue(val) {
      this._selectValue(val);
    }

    /** Restore the native <select> and remove the custom widget */
    destroy() {
      this._closePanel();
      const sel = this._select;
      sel.classList.remove("sd-hidden-select");
      sel._sdInstance = null;
      this._wrapper.parentNode.insertBefore(sel, this._wrapper);
      this._wrapper.remove();
    }
  }

  // ── Expose globally ────────────────────────────────────────────────────
  window.StyledDropdown = StyledDropdown;

  /**
   * Convenience: init all <select> elements with [data-styled] attribute
   * automatically on DOMContentLoaded.
   *
   *   <select data-styled data-grouped="true" data-placeholder="Choose subject…">
   */
  function initEl(sel) {
    if (sel._sdInstance) return;
    new StyledDropdown(sel, {
      grouped: sel.dataset.grouped === "true",
      searchable: sel.dataset.searchable === "true" ? true : undefined,
      placeholder: sel.dataset.placeholder,
    });
  }

  function autoInit() {
    document.querySelectorAll("select[data-styled]").forEach(initEl);

    // Watch for dynamic insertions
    const observer = new MutationObserver((mutations) => {
      for (const mutation of mutations) {
        for (const node of mutation.addedNodes) {
          if (node.nodeType === 1) { // Element node
            if (node.tagName === "SELECT" && node.hasAttribute("data-styled")) {
              initEl(node);
            }
            node.querySelectorAll("select[data-styled]").forEach(initEl);
          }
        }
      }
    });
    observer.observe(document.body, { childList: true, subtree: true });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", autoInit);
  } else {
    autoInit();
  }
})();
