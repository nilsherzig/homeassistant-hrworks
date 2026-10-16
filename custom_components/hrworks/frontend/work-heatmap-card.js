/*
 * work-heatmap-card: Mon-Fri calendar of worked, absent and sick days.
 *
 * type: custom:work-heatmap-card
 * entity: sensor.hr_works_work_days   # attribute days: [{date, status, worked, target, summary}]
 * show_hours: true                     # print worked hours inside each cell
 * cell_size: 36                        # square cell edge in px
 * title: null                          # text prefix in the header
 * show_header: true                    # summary line (days worked, hours)
 * show_legend: true                    # colour legend in the header
 * show_day_labels: true                # Mon..Fri labels on the left
 * show_month_labels: true              # month names above the columns
 * month_separator: true                # gap + divider between months
 * tooltip: true                        # rich hover tooltip
 * highlight_today: true                # outline today's cell
 * min_intensity: 0.35                  # lowest opacity of a worked cell (0-1)
 * colors:                              # override any of worked/leave/sick/holiday
 *   worked: "#ff6529"
 *
 * Statuses: worked (intensity = worked / target), leave, sick, holiday,
 * absent (target but nothing worked), unknown (not read yet), today.
 */
const DEFAULT_COLORS = {
  worked: "#ff6529",
  leave: "#3b82f6",
  sick: "#e5484d",
  holiday: "#8e8e93",
};
const LABELS = { worked: "worked", leave: "leave", sick: "sick", holiday: "holiday", absent: "absent" };

class WorkHeatmapCard extends HTMLElement {
  setConfig(config) {
    this._config = {
      entity: "sensor.hr_works_work_days",
      show_hours: true,
      title: null,
      cell_size: 36,
      show_header: true,
      show_legend: true,
      show_day_labels: true,
      show_month_labels: true,
      month_separator: true,
      tooltip: true,
      highlight_today: true,
      min_intensity: 0.35,
      ...config,
      colors: { ...DEFAULT_COLORS, ...Object.fromEntries(Object.entries(config.colors || {}).filter(([, v]) => v)) },
    };
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    const st = hass.states[this._config.entity];
    const sig = st ? st.last_updated : "";
    if (sig !== this._sig) {
      this._sig = sig;
      this._render();
    }
  }

  getCardSize() {
    return 3;
  }

  static getConfigForm() {
    const bool = (name) => ({ name, default: true, selector: { boolean: {} } });
    return {
      schema: [
        { name: "entity", required: true, selector: { entity: { domain: "sensor" } } },
        { name: "title", selector: { text: {} } },
        {
          type: "grid",
          name: "",
          schema: [
            { name: "cell_size", default: 36, selector: { number: { min: 16, max: 80, step: 1, mode: "box", unit_of_measurement: "px" } } },
            { name: "min_intensity", default: 0.35, selector: { number: { min: 0, max: 1, step: 0.05, mode: "slider" } } },
          ],
        },
        {
          type: "grid",
          name: "",
          schema: [
            bool("show_hours"),
            bool("show_header"),
            bool("show_legend"),
            bool("show_day_labels"),
            bool("show_month_labels"),
            bool("month_separator"),
            bool("tooltip"),
            bool("highlight_today"),
          ],
        },
        {
          type: "expandable",
          name: "colors",
          title: "Colors",
          schema: ["worked", "leave", "sick", "holiday"].map((name) => ({
            name,
            default: DEFAULT_COLORS[name],
            selector: { text: { type: "color" } },
          })),
        },
      ],
      computeLabel: (item) =>
        ({
          entity: "Work days sensor",
          title: "Title",
          cell_size: "Cell size",
          min_intensity: "Minimum intensity of worked cells",
          show_hours: "Show hours in cells",
          show_header: "Show summary header",
          show_legend: "Show legend",
          show_day_labels: "Show weekday labels",
          show_month_labels: "Show month labels",
          month_separator: "Dotted separator between months",
          tooltip: "Hover tooltip",
          highlight_today: "Highlight today",
          worked: "Worked",
          leave: "Leave",
          sick: "Sick",
          holiday: "Holiday",
        })[item.name] || item.name,
    };
  }

  static getStubConfig() {
    return { entity: "sensor.hr_works_work_days" };
  }

  _render() {
    if (!this._config || !this.shadowRoot) return;
    const c = this._config;
    const COLORS = c.colors;
    const st = this._hass && this._hass.states[c.entity];
    const rows = (st && st.attributes.days) || [];
    const lang = this._hass?.locale?.language || undefined;
    const monthFmt = new Intl.DateTimeFormat(lang, { month: "short" });
    const dayFmt = new Intl.DateTimeFormat(lang, { weekday: "short" });
    const dateFmt = new Intl.DateTimeFormat(lang, { weekday: "short", day: "numeric", month: "short" });
    const fullFmt = new Intl.DateTimeFormat(lang, { weekday: "long", day: "numeric", month: "long", year: "numeric" });
    const esc = (v) => String(v).replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");
    const parse = (iso) => new Date(`${iso}T12:00:00`);
    const pad = (v) => String(v).padStart(2, "0");
    const now = new Date();
    const todayIso = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
    const hours = (h) => (h == null ? "–" : Number.isInteger(h) ? `${h}` : h.toFixed(1));

    // Group rows into Monday-based weeks; each column holds Mon..Fri.
    const weeks = [];
    let current = null;
    for (const row of rows) {
      const d = parse(row.date);
      const monday = new Date(d);
      monday.setDate(d.getDate() - ((d.getDay() + 6) % 7));
      const wk = monday.toDateString();
      if (!current || current.key !== wk) {
        current = { key: wk, monday, cells: new Array(5).fill(null) };
        weeks.push(current);
      }
      current.cells[(d.getDay() + 6) % 7] = row;
    }

    let worked = 0;
    let total = 0;
    let cols = "";
    let months = "";
    let lastMonth = -1;
    for (const week of weeks) {
      const first = week.cells.find(Boolean);
      const wm = first ? parse(first.date).getMonth() : week.monday.getMonth();
      const sep = c.month_separator && lastMonth !== -1 && wm !== lastMonth ? " msep" : "";
      let cells = "";
      for (const row of week.cells) {
        if (!row) {
          cells += `<div class="cell empty"></div>`;
          continue;
        }
        const status = row.status === "today" ? (row.worked ? "worked" : "today") : row.status;
        const d = parse(row.date);
        let style = "";
        if (COLORS[status]) {
          let alpha = 1;
          if (status === "worked" && row.target) alpha = Math.max(c.min_intensity, Math.min(1, row.worked / row.target));
          style = `background:${COLORS[status]};opacity:${alpha.toFixed(2)}`;
        }
        if (status === "worked") {
          worked++;
          total += row.worked || 0;
        }
        const state = LABELS[status] || (status === "today" ? "today, not worked yet" : "not read yet");
        const tip = [
          fullFmt.format(d) + (row.date === todayIso ? " (today)" : ""),
          state.charAt(0).toUpperCase() + state.slice(1),
          row.worked != null ? `${hours(row.worked)} h worked${row.target ? ` of ${hours(row.target)} h target` : ""}` : null,
          row.summary || null,
        ]
          .filter(Boolean)
          .map(esc)
          .join("\n");
        const text = c.show_hours && row.worked ? hours(row.worked) : status === "sick" ? "✚" : "";
        const today = row.date === todayIso;
        cells += `<div class="cell ${status}${today && c.highlight_today ? " now" : ""}" data-tip="${tip}"><span style="${style}" class="fill"></span><span class="txt">${text}</span></div>`;
      }
      months += `<div class="mlabel${sep}">${wm !== lastMonth ? monthFmt.format(first ? parse(first.date) : week.monday) : ""}</div>`;
      lastMonth = wm;
      cols += `<div class="col${sep}">${cells}</div>`;
    }

    const labels = [0, 1, 2, 3, 4]
      .map((r) => `<div class="dlabel">${dayFmt.format(new Date(2024, 0, 8 + r))}</div>`)
      .join(""); // 2024-01-08 is a Monday
    const n = Math.max(weeks.length, 1);
    const legend = Object.entries(COLORS)
      .map(([k, v]) => `<span class="sw" style="background:${v}"></span>${LABELS[k]}`)
      .join(" ");
    const title = c.title ?? "";
    this.shadowRoot.innerHTML = `
      <style>
        :host { display: block; --cell: ${c.cell_size}px; --gap: ${Math.round(c.cell_size / 6)}px; }
        ha-card { padding: 12px 16px; overflow: hidden; }
        .head { display: flex; justify-content: space-between; align-items: baseline; flex-wrap: wrap; gap: 4px 12px;
                color: var(--secondary-text-color); font-size: 0.85em; margin-bottom: 8px; }
        .legend { display: flex; align-items: center; gap: 4px; flex-wrap: wrap; }
        .sw { width: 12px; height: 12px; border-radius: 4px; display: inline-block; margin-left: 6px; }
        .grid { display: grid; grid-template-columns: auto auto; column-gap: 8px; justify-content: start; }
        .months { display: flex; gap: var(--gap);
                  grid-column: 2; font-size: 0.75em; color: var(--secondary-text-color); height: ${c.show_month_labels ? "1.4em" : "0"}; }
        .mlabel { white-space: nowrap; width: var(--cell); flex: none; }
        .msep { margin-left: calc(var(--gap) * 2); }
        .dlabels { display: grid; grid-template-rows: repeat(5, var(--cell)); row-gap: var(--gap);
                   font-size: 0.75em; color: var(--secondary-text-color); }
        .dlabel { display: flex; align-items: center; }
        .cols { display: flex; gap: var(--gap); }
        .col { flex: none; position: relative; display: grid; grid-template-rows: repeat(5, var(--cell)); row-gap: var(--gap); }
        .cell { position: relative; width: var(--cell); height: var(--cell); border-radius: 28%;
                background: var(--divider-color); display: flex; align-items: center; justify-content: center; }
        .cell .fill { position: absolute; inset: 0; border-radius: inherit; }
        .cell .txt { position: relative; font-size: 0.72em; font-weight: 600; color: #fff;
                     text-shadow: 0 0 2px rgba(0,0,0,.6); }
        .col.msep::before { content: ""; position: absolute; top: 0; bottom: 0; left: calc(var(--gap) * -1.5 - 1px);
                            width: 0; border-left: 2px dotted var(--secondary-text-color); opacity: .6; }
        .cell { transition: transform .1s; }
        .cell:not(.empty):hover { transform: scale(1.12); z-index: 1; }
        .cell.unknown, .cell.today { background: color-mix(in srgb, var(--divider-color) 45%, transparent); }
        .cell.absent { background: transparent; box-shadow: inset 0 0 0 2px ${COLORS.sick}; }
        .cell.holiday .fill { opacity: .5 !important; }
        .cell.now { outline: 3px solid var(--primary-color); outline-offset: 2px; }
        .cell.now .txt { font-weight: 800; }
        .tip { position: fixed; display: none; z-index: 10; pointer-events: none; white-space: pre; font-size: 0.8em;
               line-height: 1.4; padding: 6px 10px; border-radius: 8px; color: var(--primary-text-color);
               background: var(--card-background-color, #fff); border: 1px solid var(--divider-color);
               box-shadow: 0 2px 8px rgba(0,0,0,.35); }
        .tip b { display: block; }
        .cell.empty { background: transparent; }
      </style>
      <ha-card>
        ${c.show_header ? `<div class="head">
          <span>${title}${title ? " · " : ""}${worked} days worked · ${hours(Math.round(total * 10) / 10)} h</span>
          ${c.show_legend ? `<span class="legend">${legend}</span>` : ""}
        </div>` : ""}
        <div class="grid">
          <div></div><div class="months">${c.show_month_labels ? months : ""}</div>
          <div class="dlabels">${c.show_day_labels ? labels : ""}</div>
          <div class="cols">${cols}</div>
        </div>
        <div class="tip"></div>
      </ha-card>`;
    const tip = this.shadowRoot.querySelector(".tip");
    for (const el of c.tooltip ? this.shadowRoot.querySelectorAll(".cell[data-tip]") : []) {
      el.addEventListener("mouseenter", () => {
        const [head, ...rest] = el.dataset.tip.split("\n");
        tip.innerHTML = `<b>${esc(head)}</b>${esc(rest.join("\n"))}`;
        tip.style.display = "block";
        const r = el.getBoundingClientRect();
        const t = tip.getBoundingClientRect();
        tip.style.left = `${Math.max(4, Math.min(innerWidth - t.width - 4, r.left + r.width / 2 - t.width / 2))}px`;
        tip.style.top = `${r.top - t.height - 8 < 4 ? r.bottom + 8 : r.top - t.height - 8}px`;
      });
      el.addEventListener("mouseleave", () => (tip.style.display = "none"));
    }
  }
}

if (!customElements.get("work-heatmap-card")) {
  customElements.define("work-heatmap-card", WorkHeatmapCard);
}
window.customCards = window.customCards || [];
window.customCards.push({
  type: "work-heatmap-card",
  name: "Work Heatmap",
  description: "Mon-Fri calendar of worked, absent and sick days",
});
