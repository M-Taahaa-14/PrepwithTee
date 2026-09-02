/* PrepWithTee — Tools + Resources dropdowns in the header.
 *
 * Tools: Built from PWT.catalogue rather than hard-coded into every HTML file.
 * Resources: Dynamically wraps the existing Resources <a> link and adds a
 * board→subject dropdown.
 *
 * Works two ways by width: hover-and-click on desktop, tap-to-expand inside
 * the stacked mobile nav. Keyboard: Enter/Space opens, Escape closes.
 */
(function () {
  "use strict";

  // ── Resources dropdown ─────────────────────────────────────────────────
  var RESOURCES = [
    {
      label: "O Level",
      items: [
        { name: "Mathematics D", code: "4024", href: "resources.html#/O%20Level%20Mathematics%204024" },
        { name: "Physics",       code: "5054", href: "resources.html#/O%20Level%20Physics%205054" },
        { name: "Chemistry",     code: "5070", href: "resources.html#/O%20Level%20Chemistry%205070" },
        { name: "Computer Science", code: "2210", href: "resources.html" },
        { name: "Islamiyat",     code: "2058", href: "resources.html" },
        { name: "Pakistan Studies", code: "2059", href: "resources.html" }
      ]
    },
    {
      label: "IGCSE",
      items: [
        { name: "Mathematics",  code: "0580", href: "resources.html#/IGCSE%20Mathematics%200580" },
        { name: "Physics",      code: "0625", href: "resources.html#/IGCSE%20Physics%200625" },
        { name: "Computer Science", code: "0478", href: "resources.html" }
      ]
    },
    {
      label: "A Level",
      items: [
        { name: "Mathematics",  code: "9709", href: "resources.html#/A%20Level%20Mathematics%209709" },
        { name: "Physics",      code: "9702", href: "resources.html#/A%20Level%20Physics%209702" }
      ]
    }
  ];

  function buildResources() {
    var resLink = document.querySelector('a.nav-link[href="resources.html"]');
    if (!resLink || resLink.dataset.resBuilt) return;
    // Don't hijack links already inside the new grouped nav structure
    if (resLink.closest('.nav-group')) return;
    resLink.dataset.resBuilt = "1";

    // Wrap the existing link in a container
    var host = document.createElement("span");
    host.className = "nav-res";
    resLink.parentNode.insertBefore(host, resLink);

    // Convert the link to a button
    var btn = document.createElement("button");
    btn.className = "nav-link";
    btn.style.cssText = "background:none;border:none;cursor:pointer;padding-bottom:2px;display:inline-flex;align-items:center;gap:4px;font-weight:600;font-size:.92rem;font-family:inherit;color:var(--ink);";
    btn.innerHTML = 'Resources';
    if (resLink.classList.contains("active")) btn.classList.add("active");
    host.appendChild(btn);
    resLink.remove();

    // Build the menu
    var menu = document.createElement("div");
    menu.className = "nav-res-menu";
    var colsHtml = '<div class="nav-res-cols">' +
      RESOURCES.map(function(board) {
        return '<div class="nav-res-col">' +
          '<div class="nav-res-col-head">' + board.label + '</div>' +
          board.items.map(function(item) {
            return '<a class="nav-res-item" href="' + item.href + '">' +
              item.name + ' <span class="res-code">' + item.code + '</span></a>';
          }).join("") +
          '</div>';
      }).join("") +
      '</div>' +
      '<a class="nav-res-all" href="resources.html">All resources →</a>';
    menu.innerHTML = colsHtml;
    host.appendChild(menu);

    // Open/close logic (mirrors tools dropdown)
    var open = false, hoverTimer = null;
    function setOpen(v) {
      open = v;
      host.dataset.open = v ? "1" : "0";
      btn.setAttribute("aria-expanded", String(v));
    }
    setOpen(false);
    btn.addEventListener("click", function(ev) { ev.preventDefault(); setOpen(!open); });

    if (window.matchMedia("(hover: hover) and (min-width: 901px)").matches) {
      host.addEventListener("mouseenter", function () { clearTimeout(hoverTimer); setOpen(true); });
      host.addEventListener("mouseleave", function () {
        hoverTimer = setTimeout(function () { setOpen(false); }, 160);
      });
    }
    document.addEventListener("click", function(ev) {
      if (open && !host.contains(ev.target)) setOpen(false);
    });
    host.addEventListener("keydown", function(ev) {
      if (ev.key === "Escape" && open) { setOpen(false); btn.focus(); }
    });
  }

  // ── Tools dropdown ─────────────────────────────────────────────────────
  function build() {
    var PWTx = window.PWT;
    if (!PWTx) return;
    var host = document.querySelector("[data-nav-tools]");
    if (!host || host.querySelector(".nav-tools-menu")) return;

    var btn = host.querySelector("[data-nav-tools-btn]");
    var menu = document.createElement("div");
    menu.className = "nav-tools-menu";
    menu.setAttribute("role", "menu");
    menu.innerHTML =
      PWTx.catalogue.map(function (t) {
        return '<a class="nav-tools-item" role="menuitem" href="' + t.href + '">' +
          '<span class="nav-tools-ico ' + t.tint + '">' + t.icon + "</span>" +
          '<span class="nav-tools-txt"><b>' + PWTx.esc(t.name) + "</b>" +
          "<span>" + PWTx.esc(t.blurb) + "</span></span></a>";
      }).join("") +
      '<a class="nav-tools-all" role="menuitem" href="tools.html">All study tools →</a>';
    host.appendChild(menu);

    var open = false, hoverTimer = null;

    function setOpen(v) {
      open = v;
      host.dataset.open = v ? "1" : "0";
      btn.setAttribute("aria-expanded", v ? "true" : "false");
    }
    setOpen(false);

    btn.addEventListener("click", function (ev) {
      ev.preventDefault();
      setOpen(!open);
    });

    // Hover only where there is a real pointer; on touch it would fire on tap
    // and fight the click handler.
    if (window.matchMedia("(hover: hover) and (min-width: 901px)").matches) {
      host.addEventListener("mouseenter", function () {
        clearTimeout(hoverTimer);
        setOpen(true);
      });
      host.addEventListener("mouseleave", function () {
        // A short grace period, so crossing the gap to the menu does not shut it.
        hoverTimer = setTimeout(function () { setOpen(false); }, 160);
      });
    }

    document.addEventListener("click", function (ev) {
      if (open && !host.contains(ev.target)) setOpen(false);
    });

    host.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape" && open) { setOpen(false); btn.focus(); return; }
      if ((ev.key === "Enter" || ev.key === " ") && ev.target === btn) {
        ev.preventDefault(); setOpen(!open); return;
      }
      if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
        var items = [].slice.call(menu.querySelectorAll("a"));
        if (!items.length) return;
        ev.preventDefault();
        if (!open) { setOpen(true); items[0].focus(); return; }
        var i = items.indexOf(document.activeElement);
        var next = ev.key === "ArrowDown"
          ? (i < 0 ? 0 : (i + 1) % items.length)
          : (i <= 0 ? items.length - 1 : i - 1);
        items[next].focus();
      }
    });

    // Mark the current page inside the dropdown, since the nav item itself is
    // now a button and cannot carry the usual .active link styling.
    var here = location.pathname.split("/").pop() || "index.html";
    menu.querySelectorAll("a").forEach(function (a) {
      if (a.getAttribute("href") === here) a.style.background = "var(--page)";
    });
    if (!PWTx.catalogue.some(function (t) { return t.href === here; }) && here !== "tools.html") {
      btn.classList.remove("active");
    }
  }

  function init() {
    build();
    buildResources();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else init();
})();

// ── Nav-group dropdowns (Notes / Past Papers / AI Assistant) ─────────────────
(function () {
  "use strict";

  function initGroups() {
    // Guard: skip if already initialised on this page
    if (document._navGroupsInit) return;
    document._navGroupsInit = true;

    document.querySelectorAll(".nav-group-btn").forEach(function (btn) {
      var group = btn.closest(".nav-group");
      var panel = group && group.querySelector(".nav-group-panel");
      if (!panel) return;

      var setOpen = function (open) {
        panel.classList.toggle("open", open);
        btn.setAttribute("aria-expanded", String(open));
      };

      btn.addEventListener("click", function (e) {
        e.stopPropagation();
        var nowOpen = !panel.classList.contains("open");
        // Close sibling groups
        document.querySelectorAll(".nav-group-panel.open").forEach(function (p) {
          if (p !== panel) {
            p.classList.remove("open");
            var b = p.closest(".nav-group") && p.closest(".nav-group").querySelector(".nav-group-btn");
            if (b) b.setAttribute("aria-expanded", "false");
          }
        });
        setOpen(nowOpen);
      });

      panel.addEventListener("click", function (e) {
        if (e.target.closest("a")) setOpen(false);
      });
    });

    document.addEventListener("click", function () {
      document.querySelectorAll(".nav-group-panel.open").forEach(function (p) {
        p.classList.remove("open");
        var b = p.closest(".nav-group") && p.closest(".nav-group").querySelector(".nav-group-btn");
        if (b) b.setAttribute("aria-expanded", "false");
      });
    });

    document.addEventListener("keydown", function (e) {
      if (e.key !== "Escape") return;
      document.querySelectorAll(".nav-group-panel.open").forEach(function (p) {
        p.classList.remove("open");
        var b = p.closest(".nav-group") && p.closest(".nav-group").querySelector(".nav-group-btn");
        if (b) b.setAttribute("aria-expanded", "false");
      });
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initGroups);
  } else {
    initGroups();
  }
})();
