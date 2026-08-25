/*
 * Paging and search for the Client Bookings Summary on the actuals reports.
 *
 * Both reports fetch their bookings as one JSON array and used to draw every
 * row into the table at once -- 700+ rows on production, with no way to find a
 * particular booking. This keeps the array in memory and renders one page of it
 * at a time.
 *
 * Presentation only. It never touches a figure: rows arrive already calculated
 * and are handed straight back to the caller's renderRow(). Filtering only
 * decides which of them are drawn.
 *
 * The two reports show different columns -- the owner's has "Created By" -- so
 * the row markup stays in each template and is passed in as a callback.
 */
(function (global) {
  "use strict";

  var DEFAULT_PAGE_SIZE = 25;

  function haystackFor(booking) {
    // Everything a person might reasonably type: the reference, the client,
    // whoever entered it, and the service names.
    var services = (booking.services || [])
      .map(function (s) { return s.service; })
      .join(" ");
    return [
      booking.booking_id,
      booking.client_name,
      booking.created_by,
      booking.booking_date,
      services,
    ].join(" ").toLowerCase();
  }

  function debounce(fn, wait) {
    var timer;
    return function () {
      var args = arguments, self = this;
      clearTimeout(timer);
      timer = setTimeout(function () { fn.apply(self, args); }, wait);
    };
  }

  /**
   * @param {Object}   opts
   * @param {Array}    opts.rows        bookings, exactly as the endpoint returned them
   * @param {Element}  opts.tbody       tbody to render into
   * @param {Element}  opts.searchInput text input to filter on
   * @param {Element}  opts.pager       container for the paging controls
   * @param {Function} opts.renderRow   booking -> "<tr>...</tr>"
   * @param {number}  [opts.pageSize]   default 25
   * @param {string}  [opts.noun]       default "bookings"
   */
  function initBookingSummary(opts) {
    var rows = opts.rows || [];
    var tbody = opts.tbody;
    var pager = opts.pager;
    var searchInput = opts.searchInput;
    var renderRow = opts.renderRow;
    var pageSize = opts.pageSize || DEFAULT_PAGE_SIZE;
    var noun = opts.noun || "bookings";
    var columnCount = (tbody.closest("table").querySelectorAll("thead th") || []).length || 1;

    // Precompute once so typing stays cheap on large result sets.
    var indexed = rows.map(function (b) {
      return { booking: b, haystack: haystackFor(b) };
    });

    var page = 1;
    var matches = indexed;

    function applySearch() {
      var term = (searchInput && searchInput.value ? searchInput.value : "")
        .trim().toLowerCase();
      matches = term
        ? indexed.filter(function (e) { return e.haystack.indexOf(term) !== -1; })
        : indexed;
    }

    function pageCount() {
      return Math.max(1, Math.ceil(matches.length / pageSize));
    }

    function renderRows() {
      if (!matches.length) {
        tbody.innerHTML =
          '<tr><td colspan="' + columnCount + '" class="text-center text-muted py-3">' +
          (indexed.length ? "No " + noun + " match your search." : "No " + noun + " to show.") +
          "</td></tr>";
        return;
      }
      var start = (page - 1) * pageSize;
      tbody.innerHTML = matches
        .slice(start, start + pageSize)
        .map(function (e) { return renderRow(e.booking); })
        .join("");
    }

    function renderPager() {
      if (!pager) return;
      var total = matches.length;
      var pages = pageCount();
      var from = total ? (page - 1) * pageSize + 1 : 0;
      var to = Math.min(page * pageSize, total);
      var showing = total
        ? "Showing " + from + "\u2013" + to + " of " + total + " " + noun
        : "No " + noun;

      pager.innerHTML =
        '<div class="d-flex flex-wrap align-items-center justify-content-between gap-2 mt-2">' +
          '<small class="text-muted">' + showing + "</small>" +
          (pages > 1
            ? '<div class="btn-group btn-group-sm" role="group" aria-label="Pagination">' +
                '<button type="button" class="btn btn-outline-secondary" data-page="prev"' +
                  (page === 1 ? " disabled" : "") + ">Previous</button>" +
                '<button type="button" class="btn btn-outline-secondary" disabled>' +
                  "Page " + page + " of " + pages + "</button>" +
                '<button type="button" class="btn btn-outline-secondary" data-page="next"' +
                  (page === pages ? " disabled" : "") + ">Next</button>" +
              "</div>"
            : "") +
        "</div>";
    }

    function draw() {
      if (page > pageCount()) page = pageCount();
      renderRows();
      renderPager();
    }

    if (pager) {
      pager.addEventListener("click", function (e) {
        var btn = e.target.closest("[data-page]");
        if (!btn) return;
        page += btn.getAttribute("data-page") === "next" ? 1 : -1;
        page = Math.min(Math.max(page, 1), pageCount());
        draw();
        // Bring the table header back into view after a page turn.
        var table = tbody.closest("table");
        if (table) table.scrollIntoView({ block: "nearest", behavior: "smooth" });
      });
    }

    if (searchInput) {
      searchInput.addEventListener("input", debounce(function () {
        applySearch();
        page = 1;          // a new search always starts at the first page
        draw();
      }, 150));
    }

    applySearch();
    draw();
  }

  global.initBookingSummary = initBookingSummary;
})(window);
