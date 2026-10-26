// Button Blueprinter: the sidebar page. Plain web component: no build step, no dependencies.
//
// Everything comes from one websocket subscription (button_blueprinter/subscribe).
// Anyone may look, test a button and set a button from the menu; the server refuses
// everything else to non-admins (switches, hand-written actions, modes, import, export).

// Must match manifest.json (a test checks).
const PAGE_VERSION = "0.7.4";

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

const RESULT = {
  ran: "Ran",
  "would run": "Would run (dry run)",
  "nothing set": "Nothing set",
  fixed: "Handled outside HA",
  off: "Switch is off",
  error: "Failed",
  "put back": "Put back",
};
const MODE = { live: "On", dry_run: "Dry run", off: "Off" };
const MODE_HELP = {
  live: "Buttons do what they're set to do.",
  dry_run: "Buttons are logged with what they would do, and nothing runs. Use this next to an old automation to compare.",
  off: "Button Blueprinter ignores this switch.",
};
const COMMAND = {
  play_pause: "Play or pause",
  next: "Next track",
  previous: "Previous track",
  volume_up: "Volume up",
  volume_down: "Volume down",
  mute: "Mute or unmute",
  vacuum: "Vacuum",
  vac_and_mop: "Vacuum and mop",
  mop: "Mop",
  red: "Red",
  orange: "Orange",
  yellow: "Yellow",
  green: "Green",
  blue: "Blue",
  violet: "Violet",
  warm_white: "Warm white",
};
// The D-Life display's colours, as near as a screen gets.
const DISPLAY_COLOUR = { white: "#f2f2f2", green: "#4cd964", blue: "#4aa3ff", red: "#ff5a5a", orange: "#ff9f43", yellow: "#ffd84a" };
const SHOW_LABEL = { icon: "Icon only", icon_name: "Icon and name", none: "Nothing" };
const ICON_URL = "/button_blueprinter_icons";
// Where a look the page can't set is really changed.
const WHERE = { ets: "ETS", insert: "a new insert" };

const FIELD_LABEL = {
  entities: "What",
  entity: "Which",
  scene: "Scene",
  script: "Script",
  brightness: "Brightness (%)",
  step: "Step (%)",
  again_off: "Pressing it again turns its lights off",
  command: "Do",
  vacuum: "Robot",
  area: "Area to clean",
  mode: "Cleaning",
  colour: "Colour",
  fade: "Fade (seconds)",
};

function s_label(sw, c) {
  const label = sw.looks?.[c.id]?.label;
  return label ? `${c.name} (${label})` : c.name;
}

function time(iso) {
  try {
    return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } catch (e) {
    return iso;
  }
}

class ButtonBlueprinterPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._data = null;
    this._error = null;
    this._tab = "rooms";
    this._sheet = null; // {switch, control}
    this._want = null; // the look being asked for: {switch, control, look}
    this._edit = null; // binding editor: {gesture, kind, values, json, error}
    this._form = null; // switch form: a switch's fields plus {error, notes, exported}
    this._flash = {}; // "switch/control" -> when it was last pressed
    this._lastAt = null;
    this._unsub = null;
    this.shadowRoot.addEventListener("click", (e) => this._click(e));
    this.shadowRoot.addEventListener("change", (e) => this._change(e));
    this.shadowRoot.addEventListener("input", (e) => this._input(e));
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first) {
      this._subscribe();
      this._render();
    }
  }
  set narrow(v) {
    this._narrow = v;
  }

  connectedCallback() {
    if (this._hass && !this._unsub) this._subscribe();
  }
  disconnectedCallback() {
    if (this._unsub) this._unsub.then((u) => u && u()).catch(() => {});
    this._unsub = null;
  }

  _subscribe() {
    this._unsub = this._hass.connection
      .subscribeMessage(
        (data) => {
          this._data = data;
          this._error = data.error ? "Button Blueprinter isn't set up. Add it under Settings → Devices & services." : null;
          this._noteFlashes();
          if (!this._busy()) this._render();
        },
        { type: "button_blueprinter/subscribe" }
      )
      .catch((err) => {
        this._error = err.message || String(err);
        this._unsub = null;
        this._render();
      });
  }

  _busy() {
    // Never redraw under someone typing.
    const a = this.shadowRoot.activeElement;
    return !!a && ["INPUT", "TEXTAREA"].includes(a.tagName);
  }

  _noteFlashes() {
    const log = this._data?.log || [];
    const newest = log.length ? log[log.length - 1].at : null;
    if (this._lastAt && newest) {
      for (const e of log) if (e.at > this._lastAt) this._flash[`${e.switch}/${e.control}`] = Date.now();
      if (newest > this._lastAt) setTimeout(() => !this._busy() && this._render(), 1600);
    }
    this._lastAt = newest;
  }

  // ---- helpers ------------------------------------------------------------------------

  _ws(msg) {
    return this._hass.connection.sendMessagePromise(msg);
  }
  get _admin() {
    return !!this._data?.is_admin;
  }
  _model(id) {
    return (this._data?.models || []).find((m) => m.id === id);
  }
  _switch(id) {
    return (this._data?.switches || []).find((s) => s.id === id);
  }
  _name(entityId) {
    return this._hass?.states?.[entityId]?.attributes?.friendly_name || entityId;
  }
  _entities(domains) {
    return Object.keys(this._hass?.states || {})
      .filter((e) => domains.includes(e.split(".")[0]))
      .sort((a, b) => this._name(a).localeCompare(this._name(b)));
  }
  _gesture(g) {
    return this._data?.gestures?.[g] || g;
  }
  _areaName(id) {
    return (this._data?.areas || []).find((a) => a.id === id)?.name;
  }

  _icon(setId, iconId) {
    return this._data?.icon_sets?.[setId]?.icons?.find((i) => i.id === iconId);
  }
  _setIcons(m) {
    const all = this._data?.icon_sets?.[m.icon_set]?.icons || [];
    return all.filter((i) => (!m.icon_only?.length || m.icon_only.includes(i.id)) && (!m.display || i.ets != null));
  }
  // An icon from a set: the real picture if it's installed in HA, else its look-alike.
  _iconHtml(setId, iconId, colour, cls = "") {
    const icon = this._icon(setId, iconId);
    if (!icon) return "";
    const real = icon.file && (this._data?.icon_files?.[setId] || []).includes(icon.id);
    if (real) {
      const url = `${ICON_URL}/${encodeURIComponent(setId)}/${encodeURIComponent(icon.file)}`;
      return `<span class="sicon ${cls}" role="img" aria-label="${esc(icon.name)}" style="-webkit-mask:url('${url}') center/contain no-repeat;mask:url('${url}') center/contain no-repeat;background:${colour}"></span>`;
    }
    return `<ha-icon class="${cls}" icon="${esc(icon.mdi)}" title="${esc(icon.name)}" style="color:${colour}"></ha-icon>`;
  }
  // What a button on a display plate shows now: its look for the current status.
  _displayLook(s, m, c) {
    const look = { ...(m.display.defaults || {}), ...(s.looks?.[c.id] || {}) };
    const on = s.leds_now?.[c.id] === 1;
    return {
      on,
      show: look.show || "icon",
      label: look.label || "",
      icon: on ? look.icon_on : look.icon_off,
      colour: DISPLAY_COLOUR[on ? look.colour_on : look.colour_off] || DISPLAY_COLOUR.white,
    };
  }

  _describe(binding) {
    if (!binding) return "";
    if (binding.actions) return `Set by hand (${binding.actions.length} action${binding.actions.length === 1 ? "" : "s"})`;
    const m = binding.menu || {};
    const names = (ids) => (ids || []).map((e) => this._name(e)).join(", ");
    const fade = m.fade !== undefined ? ` (fade ${m.fade} s)` : "";
    switch (m.kind) {
      case "toggle":
        return `Switch on or off: ${names(m.entities)}`;
      case "turn_on":
        return `Switch on${m.brightness ? ` at ${m.brightness} %` : ""}: ${names(m.entities)}`;
      case "turn_off":
        return `Switch off: ${names(m.entities)}`;
      case "scene":
        return `Scene: ${this._name(m.scene)}${m.again_off ? " (again turns it off)" : ""}`;
      case "brighter":
        return `Brighter by ${m.step || 10} %: ${names(m.entities)}${fade}`;
      case "dimmer":
        return `Dimmer by ${m.step || 10} %: ${names(m.entities)}${fade}`;
      case "colour":
        return `${COMMAND[m.colour] || m.colour}: ${names(m.entities)}${fade}`;
      case "put_back":
        return "Put things back now";
      case "media":
        return `${COMMAND[m.command] || m.command}: ${this._name(m.entity)}`;
      case "script":
        return `Run ${this._name(m.script)}`;
      case "vacuum":
        return `${COMMAND[m.mode] || m.mode}: ${this._areaName(m.area) || m.area} with ${this._name(m.vacuum)} (again sends it home)`;
      default:
        return m.kind || "";
    }
  }

  // ---- drawing --------------------------------------------------------------------------

  _render() {
    const d = this._data;
    const body = this._error
      ? `<p class="error">${esc(this._error)}</p>`
      : !d
        ? `<p class="muted">Loading…</p>`
        : this._tab === "log"
          ? this._renderLog()
          : this._tab === "waiting"
            ? this._renderWaiting()
            : this._renderRooms();
    const notes = [];
    if (d && d.version && d.version !== PAGE_VERSION) notes.push("Button Blueprinter was updated. Reload this page.");
    if (d?.model_errors?.length) notes.push(`Some model files didn't load: ${d.model_errors.join("; ")}`);
    if (d && d.knx && !["not needed", "listening"].includes(d.knx)) notes.push(`KNX: ${d.knx}`);
    if (d && d.mqtt && !["not needed", "listening"].includes(d.mqtt)) notes.push(`Zigbee2MQTT: ${d.mqtt}`);
    const sheetTop = this.shadowRoot.querySelector(".sheet")?.scrollTop || 0;
    this.shadowRoot.innerHTML = `
      <style>${STYLE}</style>
      <div class="top">
        <h1>Button Blueprinter</h1>
        <nav>
          <button class="tab ${this._tab === "rooms" ? "on" : ""}" data-tab="rooms">Rooms</button>
          <button class="tab ${this._tab === "waiting" ? "on" : ""}" data-tab="waiting">Waiting for ETS${this._waitingCount() ? ` (${this._waitingCount()})` : ""}</button>
          <button class="tab ${this._tab === "log" ? "on" : ""}" data-tab="log">What happened</button>
          ${this._admin && this._tab === "rooms" ? `<button class="primary" data-act="new-switch">Add a switch</button>` : ""}
        </nav>
      </div>
      <main>
        ${notes.map((n) => `<p class="warn">${esc(n)}</p>`).join("")}
        ${body}
      </main>
      ${this._sheet ? this._renderSheet() : ""}
      ${this._form ? this._renderForm() : ""}
      ${this._edit ? this._renderEditor() : ""}`;
    const sheet = this.shadowRoot.querySelector(".sheet");
    if (sheet && sheetTop) sheet.scrollTop = sheetTop; // a redraw keeps the sheet where it was
  }

  _renderRooms() {
    const d = this._data;
    if (!d.switches.length)
      return `<p class="muted">No switches yet.${this._admin ? " Use “Add a switch” to start." : " An administrator adds them."}</p>`;
    const groups = new Map();
    for (const s of d.switches) {
      const key = s.area_id && this._areaName(s.area_id) ? s.area_id : "";
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(s);
    }
    const keys = [...groups.keys()].sort((a, b) => (!a ? 1 : !b ? -1 : this._areaName(a).localeCompare(this._areaName(b))));
    return keys
      .map(
        (k) => `<section>
          <h2>${esc(k ? this._areaName(k) : "No room")}</h2>
          <div class="switches">${groups.get(k).map((s) => this._renderSwitch(s)).join("")}</div>
        </section>`
      )
      .join("");
  }

  _renderSwitch(s) {
    const m = this._model(s.model);
    const mode = this._admin
      ? `<select data-mode="${esc(s.id)}" title="${esc(MODE_HELP[s.mode])}" aria-label="Mode">${Object.entries(MODE)
          .map(([k, v]) => `<option value="${k}" ${k === s.mode ? "selected" : ""}>${v}</option>`)
          .join("")}</select>`
      : `<span class="pill mode-${esc(s.mode)}" title="${esc(MODE_HELP[s.mode])}">${MODE[s.mode]}</span>`;
    return `<article class="card">
      <header>
        <div><b>${esc(s.name)}</b><div class="muted small">${esc(m ? `${m.maker} ${m.name}` : s.model)}${s.knx?.address ? ` · ${esc(s.knx.address)}` : ""}</div></div>
        <div class="row">${mode}${this._admin ? `<button class="icon" data-act="edit-switch" data-switch="${esc(s.id)}" title="Change this switch" aria-label="Change this switch">⚙</button>` : ""}</div>
      </header>
      ${s.problems?.length ? `<p class="warn small">${s.problems.map(esc).join("<br>")}</p>` : ""}
      ${m ? this._picture(s, m) : ""}
      ${this._renderPutBack(s)}
      ${m?.notes ? `<p class="muted small">${esc(m.notes)}</p>` : ""}
    </article>`;
  }

  _renderPutBack(s) {
    if (!s.put_back) return "";
    if (!s.put_back_until)
      return `<p class="muted small">Puts lights back ${s.put_back.minutes} min after the last press.</p>`;
    const at = new Date(s.put_back_until).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    return `<div class="row small"><span>Puts ${esc(s.put_back_lights.join(", "))} back at ${esc(at)}</span>
      <button data-act="put-back" data-switch="${esc(s.id)}">Put back now</button></div>`;
  }

  _picture(s, m) {
    const p = m.picture;
    const W = p.width;
    const H = p.height;
    const pct = (v, of) => `${(v / of) * 100}%`;
    const box = (c) =>
      c.shape === "rect"
        ? `left:${pct(c.x, W)};top:${pct(c.y, H)};width:${pct(c.w, W)};height:${pct(c.h, H)}`
        : `left:${pct(c.cx - c.r, W)};top:${pct(c.cy - c.r, H)};width:${pct(2 * c.r, W)};height:${pct(2 * c.r, H)}`;
    const decor = (p.decor || [])
      .map((c) => `<div class="decor ${c.shape === "rect" ? "" : "round"}" style="${box(c)};border-color:${esc(p.ink || "#888")}"></div>`)
      .join("");
    const controls = m.controls
      .map((c) => {
        const looks = s.looks?.[c.id] || {};
        const bound = Object.keys(s.bindings?.[c.id] || {}).length;
        const fixed = Object.keys(s.fixed?.[c.id] || {}).length;
        const lit = s.leds_now?.[c.id] === 1;
        const waiting = !!s.waiting?.[c.id];
        const flash = Date.now() - (this._flash[`${s.id}/${c.id}`] || 0) < 1500;
        const hole = c.shape === "ring" ? (c.inner / c.r) * 100 : 0;
        const mask = c.shape === "ring" ? `radial-gradient(circle closest-side, transparent ${hole}%, #000 calc(${hole}% + 1px))` : "";
        const ring = mask ? `-webkit-mask:${mask};mask:${mask};` : "";
        const label = looks.label || (c.shape === "ring" ? c.name : c.name.replace(/^Button /, ""));
        let inside;
        if (m.display) {
          const d = this._displayLook(s, m, c);
          const text = d.show === "icon_name" && d.label ? `<span class="disptext" style="color:${d.colour}">${esc(d.label)}</span>` : "";
          inside = d.show === "none" ? "" : `${this._iconHtml(m.icon_set, d.icon, d.colour, "disp")}${text}`;
        } else if (m.icon_set) {
          inside = looks.icon
            ? `${this._iconHtml(m.icon_set, looks.icon, p.ink || "#222", "insert")}${looks.label ? `<span class="note">${esc(looks.label)}</span>` : ""}`
            : `<span>${esc(label)}</span>`;
        } else {
          inside =
            c.shape === "ring"
              ? `<span class="ringlabel">${esc(label)}</span>`
              : `${looks.icon ? `<ha-icon icon="${esc(looks.icon)}"></ha-icon>` : ""}<span>${esc(label)}</span>`;
        }
        return `<button class="ctl ${c.shape} ${m.display ? "onscreen" : ""} ${bound ? "bound" : ""} ${fixed ? "fixed" : ""} ${flash ? "flash" : ""} ${waiting ? "waiting" : ""}"
            style="${box(c)};${ring}color:${esc(p.ink || "#222")}" data-act="control" data-switch="${esc(s.id)}" data-control="${esc(c.id)}"
            title="${esc(c.name)}${waiting ? " (a change is waiting)" : ""}" aria-label="${esc(`${c.name}${looks.label ? `: ${looks.label}` : ""}${waiting ? ", a change is waiting" : ""}`)}">
          ${inside}${lit ? `<i class="led" title="LED on"></i>` : ""}${waiting ? `<i class="wait" title="A change is waiting"></i>` : ""}
        </button>`;
      })
      .join("");
    const width = Math.min(260, Math.max(120, W * 2.4));
    const radius = `${(p.radius / W) * 100}% / ${(p.radius / H) * 100}%`;
    // A display plate: buttons down both edges, the display between them.
    const screen = m.display ? `<div class="screen"></div><div class="edge left"></div><div class="edge right"></div>` : "";
    return `<div class="plate ${m.display ? "dynamic" : ""}" style="aspect-ratio:${W} / ${H};width:${width}px;max-width:100%;background:${esc(p.colour || "#ddd")};border-radius:${radius}">${screen}${decor}${controls}</div>`;
  }

  _renderSheet() {
    const s = this._switch(this._sheet.switch);
    const m = s && this._model(s.model);
    const c = m?.controls.find((x) => x.id === this._sheet.control);
    if (!c) return "";
    const looks = s.looks?.[c.id] || {};
    const rows = c.gestures
      .map((g) => {
        const fixed = s.fixed?.[c.id]?.[g];
        const b = s.bindings?.[c.id]?.[g];
        const canEdit = !fixed && (this._admin || !b || !b.actions);
        const what = fixed
          ? `<span class="fixedtext">Handled outside Home Assistant: ${esc(fixed)}</span>`
          : b
            ? esc(this._describe(b))
            : `<span class="muted">Nothing</span>`;
        return `<tr>
          <th>${esc(this._gesture(g))}</th>
          <td>${what}</td>
          <td class="acts">
            ${canEdit ? `<button data-act="edit-binding" data-gesture="${esc(g)}">${b ? "Change" : "Set"}</button>` : ""}
            ${b && canEdit ? `<button data-act="clear-binding" data-gesture="${esc(g)}">Clear</button>` : ""}
            ${!fixed ? `<button data-act="test" data-gesture="${esc(g)}" title="Act as if this happened now">Test</button>` : ""}
            ${this._admin && !b ? `<button data-act="fix" data-gesture="${esc(g)}" title="Done outside Home Assistant (KNX-direct, say)">${fixed ? "Not fixed" : "Fixed"}</button>` : ""}
          </td>
        </tr>`;
      })
      .join("");
    const address = s.addresses?.[c.id];
    let extra = "";
    const where = m.display ? "ets" : m.icon_set ? "insert" : null;
    if (where) extra += this._renderLookRequest(s, m, c, where);
    else if (this._admin)
      extra += `<h3>How it looks</h3>
        <div class="grid2">
          <label>Label <input data-look="label" value="${esc(looks.label || "")}" placeholder="${esc(c.name)}"></label>
          <label>Icon <input data-look="icon" value="${esc(looks.icon || "")}" placeholder="mdi:lightbulb"></label>
        </div>
        <div class="row end"><button class="primary" data-act="save-looks">Save</button></div>`;
    if (this._admin && m.input === "knx" && m.knx.led)
      extra += `<h3>${m.display ? "Status (picks the on or off look)" : "LED"}</h3><div class="grid2">
          <label>${m.display ? "On while" : "Lit while"} <input data-led="entity_id" list="bb-all" value="${esc(s.leds?.[c.id]?.entity_id || "")}" placeholder="binary_sensor.…"></label>
          <label>is <input data-led="state" value="${esc(s.leds?.[c.id]?.state || "on")}"></label>
        </div>
        <div class="row end"><button class="primary" data-act="save-led">Save</button></div>
        <datalist id="bb-all">${Object.keys(this._hass.states)
          .sort()
          .map((e) => `<option value="${esc(e)}">${esc(this._name(e))}</option>`)
          .join("")}</datalist>`;
    return `<div class="backdrop" data-act="close-sheet"></div>
      <div class="sheet" role="dialog" aria-label="${esc(c.name)}">
        <header><b>${esc(s.name)} · ${esc(c.name)}${looks.label && looks.label !== c.name ? ` (${esc(looks.label)})` : ""}</b><button class="icon" data-act="close-sheet" aria-label="Close">✕</button></header>
        ${address ? `<p class="muted small">${Object.entries(address).map(([k, v]) => `${esc(k)} ${esc(v)}`).join(" · ")}</p>` : ""}
        ${s.mode === "dry_run" ? `<p class="warn small">This switch is in a dry run: presses are only logged.</p>` : ""}
        <table class="gestures">${rows}</table>
        ${extra}
      </div>`;
  }

  // A look drawn small: a display button's on and off looks, or an insert.
  _lookPreview(m, look) {
    if (m.display) {
      const full = { ...(m.display.defaults || {}), ...(look || {}) };
      const pv = (st) => {
        const colour = DISPLAY_COLOUR[full["colour_" + st]] || DISPLAY_COLOUR.white;
        const text = full.show === "icon_name" && full.label ? `<span class="disptext" style="color:${colour}">${esc(full.label)}</span>` : "";
        return `<span class="pv"><span class="pvscreen">${full.show === "none" ? "" : this._iconHtml(m.icon_set, full["icon_" + st], colour, "disp") + text}</span>${st === "on" ? "On" : "Off"}</span>`;
      };
      return `<span class="preview">${pv("on")}${pv("off")}</span>`;
    }
    const p = m.picture || {};
    const icon = look?.icon ? this._iconHtml(m.icon_set, look.icon, p.ink || "#222", "insert") : `<span class="muted small">No insert</span>`;
    return `<span class="preview"><span class="pv"><span class="pvinsert" style="background:${esc(p.colour || "#ddd")}">${icon}</span>${look?.icon ? esc(this._icon(m.icon_set, look.icon)?.name || "") : ""}</span></span>`;
  }

  _changesTable(w) {
    if (!w?.changes?.length) return "";
    return `<table class="changes"><tr><th>${w.where === "ets" ? "ETS setting" : "What"}</th><th>Now</th><th>Change to</th></tr>${w.changes
      .map((x) => `<tr><td>${esc(x.setting)}</td><td>${esc(x.from)}</td><td><b>${esc(x.to)}</b></td></tr>`)
      .join("")}</table>`;
  }

  _renderLookRequest(s, m, c, where) {
    const plate = s.looks?.[c.id] || {};
    const request = s.wanted?.[c.id];
    if (!this._want || this._want.switch !== s.id || this._want.control !== c.id)
      this._want = { switch: s.id, control: c.id, look: { ...(m.display?.defaults || {}), ...plate, ...(request?.look || {}) } };
    const look = this._want.look;
    let fields;
    if (m.display) {
      const d = m.display;
      const icons = this._setIcons(m);
      const iconSel = (key) =>
        `<select data-want="${key}">${icons.map((i) => `<option value="${esc(i.id)}" ${i.id === look[key] ? "selected" : ""}>${esc(i.name)}</option>`).join("")}</select>`;
      const colourSel = (key) =>
        `<select data-want="${key}">${d.colours.map((x) => `<option value="${x}" ${x === look[key] ? "selected" : ""}>${x[0].toUpperCase() + x.slice(1)}</option>`).join("")}</select>`;
      fields = `<div class="grid2">
          <label>Name (up to ${d.label_max}) <input data-want="label" maxlength="${d.label_max}" value="${esc(look.label || "")}"></label>
          <label>Shows <select data-want="show">${d.show.map((x) => `<option value="${x}" ${x === look.show ? "selected" : ""}>${SHOW_LABEL[x]}</option>`).join("")}</select></label>
          <label>Icon when on ${iconSel("icon_on")}</label>
          <label>Colour when on ${colourSel("colour_on")}</label>
          <label>Icon when off ${iconSel("icon_off")}</label>
          <label>Colour when off ${colourSel("colour_off")}</label>
        </div>`;
    } else {
      fields = `<div class="grid2">
          <label>Insert <select data-want="icon"><option value="">None</option>${this._setIcons(m)
            .map((i) => `<option value="${esc(i.id)}" ${i.id === look.icon ? "selected" : ""}>${esc(i.name)}</option>`)
            .join("")}</select></label>
          <label>Note (this page only) <input data-want="label" value="${esc(look.label || "")}"></label>
        </div>`;
    }
    const w = s.waiting?.[c.id];
    const waiting = request
      ? `<div class="waitbox">
          <b>Waiting for ${WHERE[where]}${this._inEtsPill(request)}</b>
          <span class="muted small">Asked by ${esc(request.by || "someone")}${request.at ? `, ${esc(time(request.at))}` : ""}</span>
          ${this._lookPreview(m, request.look)}
          ${w?.function ? `<p class="small">In ETS: ${esc(s.knx?.address || "this plate")}, ${esc(w.function)}</p>` : ""}
          ${this._changesTable(w)}
          ${this._waitButtons(s, c.id, request, where)}
        </div>`
      : "";
    return `<h3>How it looks</h3>
      <div class="lookrow"><span class="muted small rowlabel">On the plate now</span>${this._lookPreview(m, plate)}</div>
      ${waiting}
      <h3>${request ? "Change the request" : "Ask for a change"}</h3>
      <p class="muted small">${
        where === "ets"
          ? "Icons, colours and names are set in ETS, so a change waits on the “Waiting for ETS” list until the plate has been updated. What the button does changes straight away."
          : "The plate shows a printed insert, so a change waits on the “Waiting for ETS” list until a new insert is in."
      }</p>
      ${fields}
      <div class="lookrow"><span class="muted small rowlabel">Would look like</span><span class="wantpreview">${this._lookPreview(m, look)}</span></div>
      <div class="row end">${this._want.note ? `<span class="muted small" role="status">${esc(this._want.note)}</span>` : ""}<button class="primary" data-act="ask-look">${request ? "Change the request" : "Ask for this"}</button></div>`;
  }

  // "In ETS": set in ETS but not downloaded yet, so several buttons can go down in one download.
  _inEtsPill(request) {
    if (!request?.in_ets) return "";
    const by = `Marked by ${request.in_ets.by || "someone"}${request.in_ets.at ? `, ${time(request.in_ets.at)}` : ""}`;
    return ` <span class="pill in-ets" title="${esc(by)}">In ETS, not downloaded</span>`;
  }
  _waitButtons(s, control, request, where) {
    const ids = `data-switch="${esc(s.id)}" data-control="${esc(control)}"`;
    const mark =
      this._admin && where === "ets"
        ? request?.in_ets
          ? `<button data-act="mark-in-ets" data-on="0" ${ids} aria-pressed="true">Not in ETS yet</button>`
          : `<button data-act="mark-in-ets" data-on="1" ${ids} aria-pressed="false">In ETS</button>`
        : "";
    return `<div class="row end">
      <button data-act="withdraw-look" ${ids}>Withdraw</button>
      ${mark}
      ${this._admin ? `<button class="primary" data-act="finish-look" ${ids}>It's done</button>` : ""}
    </div>`;
  }

  _waitingCount() {
    return (this._data?.switches || []).reduce((n, s) => n + Object.keys(s.waiting || {}).length, 0);
  }

  _renderWaiting() {
    const list = (this._data.switches || []).filter((s) => Object.keys(s.waiting || {}).length);
    if (!list.length) return `<p class="muted">Nothing is waiting. Ask for a new icon, colour or name from a button on the Rooms tab.</p>`;
    const intro = `<p class="muted">Looks people have asked for that only ETS (or a new printed insert) can give. A request is ticked off by itself when a fresh read of ETS shows the plate matches${
      this._admin ? ", or press “It's done”" : ""
    }.</p>`;
    return (
      intro +
      list
        .map((s) => {
          const m = this._model(s.model);
          const cards = Object.entries(s.waiting)
            .map(([control, w]) => {
              const request = s.wanted?.[control] || {};
              return `<div class="waitcard ${request.in_ets ? "in-ets" : ""}">
                <header><b>${esc(w.button)}</b>${w.function ? ` <span class="muted small">ETS ${esc(s.knx?.address || "")} · ${esc(w.function)}</span>` : ""}${this._inEtsPill(request)}</header>
                <span class="muted small">Asked by ${esc(request.by || "someone")}${request.at ? `, ${esc(time(request.at))}` : ""}</span>
                <div class="lookrow"><span class="muted small rowlabel">Now</span>${m ? this._lookPreview(m, s.looks?.[control]) : ""}</div>
                <div class="lookrow"><span class="muted small rowlabel">Asked for</span>${m ? this._lookPreview(m, request.look) : ""}</div>
                ${this._changesTable(w)}
                ${this._waitButtons(s, control, request, w.where)}
              </div>`;
            })
            .join("");
          const area = s.area_id ? this._areaName(s.area_id) : "";
          const total = Object.keys(s.waiting).length;
          const marked = Object.keys(s.waiting).filter((c) => s.wanted?.[c]?.in_ets).length;
          const progress = marked
            ? `<div class="row inets-bar"><span class="small">${marked} of ${total} in ETS, waiting for a download</span>${
                this._admin ? `<button class="primary" data-act="finish-in-ets" data-switch="${esc(s.id)}" data-count="${marked}">Downloaded: tick off ${marked}</button>` : ""
              }</div>`
            : "";
          return `<h2>${esc(s.name)}${area && area !== s.name ? ` <span class="muted small">${esc(area)}</span>` : ""}</h2>${progress}<div class="waitlist">${cards}</div>`;
        })
        .join("")
    );
  }

  _renderEditor() {
    const e = this._edit;
    const menu = this._data.menu;
    // "Put things back now" only means something on a switch that puts things back.
    const putsBack = !!this._switch(this._sheet?.switch)?.put_back;
    const kinds = Object.entries(menu)
      .filter(([k]) => k !== "put_back" || putsBack || e.kind === k)
      .map(([k, v]) => `<option value="${k}" ${k === e.kind ? "selected" : ""}>${esc(v.label)}</option>`)
      .join("");
    let fields = "";
    if (e.kind === "__actions") {
      fields = `<label>Actions, as JSON (a list of Home Assistant actions)
        <textarea data-json rows="10" spellcheck="false">${esc(e.json)}</textarea></label>
        <p class="muted small">Variables you can use: <code>steps</code> (how far a dial turned), <code>gesture</code>, <code>control</code>, <code>switch</code>.</p>`;
    } else if (menu[e.kind]) {
      fields = Object.entries(menu[e.kind].fields)
        .map(([name, rule]) => this._field(name, rule, e.values[name]))
        .join("");
    }
    return `<div class="backdrop top2" data-act="close-editor"></div>
      <div class="dialog" role="dialog" aria-label="Set a button">
        <header><b>${esc(this._gesture(e.gesture))}</b><button class="icon" data-act="close-editor" aria-label="Close">✕</button></header>
        <label>What it does <select data-kind>
          <option value="" ${!e.kind ? "selected" : ""}>Choose…</option>${kinds}
          ${this._admin ? `<option value="__actions" ${e.kind === "__actions" ? "selected" : ""}>Write actions by hand…</option>` : ""}
        </select></label>
        ${fields}
        ${e.error ? `<p class="error">${esc(e.error)}</p>` : ""}
        <div class="row end"><button data-act="close-editor">Cancel</button><button class="primary" data-act="save-binding" ${e.kind ? "" : "disabled"}>Save</button></div>
      </div>`;
  }

  _field(name, rule, value) {
    const [type, opts] = rule;
    const label = FIELD_LABEL[name] || name;
    if (type === "entities") {
      const chosen = value || [];
      const chips = chosen
        .map((id) => `<span class="chip">${esc(this._name(id))}<button class="x" data-act="unpick" data-field="${name}" data-id="${esc(id)}" aria-label="Remove">✕</button></span>`)
        .join("");
      const options = this._entities(opts)
        .filter((id) => !chosen.includes(id))
        .map((id) => `<option value="${esc(id)}">${esc(this._name(id))}</option>`)
        .join("");
      return `<div class="field"><span>${esc(label)}</span>
        <div class="chips">${chips || `<span class="muted small">Nothing chosen</span>`}</div>
        <select data-pick="${name}"><option value="">Add…</option>${options}</select></div>`;
    }
    if (type === "entity")
      return `<label>${esc(label)} <select data-val="${name}"><option value="">Choose…</option>${this._entities(opts)
        .map((id) => `<option value="${esc(id)}" ${id === value ? "selected" : ""}>${esc(this._name(id))}</option>`)
        .join("")}</select></label>`;
    if (type === "percent")
      return `<label>${esc(label)} <input type="number" min="1" max="100" data-val="${name}" value="${esc(value ?? "")}" placeholder="${name === "step" ? "10" : "as it was"}"></label>`;
    if (type === "area")
      return `<label>${esc(label)} <select data-val="${name}"><option value="">Choose…</option>${(this._data?.areas || [])
        .slice()
        .sort((a, b) => a.name.localeCompare(b.name))
        .map((a) => `<option value="${esc(a.id)}" ${a.id === value ? "selected" : ""}>${esc(a.name)}</option>`)
        .join("")}</select></label>`;
    if (type === "seconds")
      return `<label>${esc(label)} <input type="number" min="0" max="10" step="0.1" data-val="${name}" value="${esc(value ?? "")}" placeholder="the light's own"></label>`;
    if (type === "bool") return `<label class="check"><input type="checkbox" data-bool="${name}" ${value ? "checked" : ""}> ${esc(label)}</label>`;
    if (type === "choice")
      return `<label>${esc(label)} <select data-val="${name}"><option value="">Choose…</option>${opts
        .map((o) => `<option value="${o}" ${o === value ? "selected" : ""}>${esc(COMMAND[o] || o)}</option>`)
        .join("")}</select></label>`;
    return "";
  }

  _renderPutBackForm(f, m) {
    // Opt-in: one tickbox unless this switch is set to put things back.
    const pb = f.put_back;
    const tick = `<label class="check"><input type="checkbox" data-pb-on ${pb ? "checked" : ""}> Put lights back after a while (a play or task switch)</label>`;
    if (!pb) return tick;
    const only = pb.controls || [];
    return `${tick}
      <p class="muted small">After this many minutes without a press, the lights its buttons changed go back the way they were. A light changed another way in the meantime is left alone.</p>
      <label>Minutes <input type="number" min="1" max="1440" data-pb="minutes" value="${esc(pb.minutes || "")}"></label>
      <p class="muted small">Only these buttons (none ticked: all of them):</p>
      <div class="row">${m.controls
        .map((c) => `<label class="check"><input type="checkbox" data-pb-control="${esc(c.id)}" ${only.includes(c.id) ? "checked" : ""}> ${esc(s_label(f, c))}</label>`)
        .join("")}</div>`;
  }

  _renderForm() {
    const f = this._form;
    const m = this._model(f.model);
    const models = this._data.models
      .map((x) => `<option value="${esc(x.id)}" ${x.id === f.model ? "selected" : ""}>${esc(`${x.maker} ${x.name}`)}</option>`)
      .join("");
    const areas = this._data.areas
      .slice()
      .sort((a, b) => a.name.localeCompare(b.name))
      .map((a) => `<option value="${esc(a.id)}" ${a.id === f.area_id ? "selected" : ""}>${esc(a.name)}</option>`)
      .join("");
    let inputs = "";
    if (m?.input === "knx") {
      const k = f.knx || {};
      inputs = `<h3>KNX</h3>
        <p class="muted small">The address of the first button for each kind of telegram; the other buttons follow on.</p>
        <div class="grid2">
          <label>Taps start at <input data-knx="tap" value="${esc(k.tap || "")}" placeholder="6/0/40"></label>
          ${m.knx.hold ? `<label>Holds start at <input data-knx="hold" value="${esc(k.hold || "")}" placeholder="6/1/40"></label>` : ""}
          ${m.knx.led ? `<label>LEDs start at <input data-knx="led" value="${esc(k.led || "")}" placeholder="6/2/40"></label>` : ""}
          <label>The plate's own address <input data-knx="address" value="${esc(k.address || "")}" placeholder="1.1.31"></label>
        </div>`;
    } else if (m?.input === "zigbee2mqtt") {
      // This model's own devices first, then every other Zigbee2MQTT device.
      const all = this._data.z2m_devices || [];
      const fits = (dv) => !m.match?.length || m.match.includes(dv.model_id);
      const option = (dv) =>
        `<option value="${esc(dv.id)}" ${f.device === dv.id ? "selected" : ""}>${esc(dv.name)}${dv.model ? ` (${esc(dv.model)})` : ""}</option>`;
      inputs = `<h3>Where its presses come from</h3>
        <p class="muted small">The device's own Zigbee2MQTT messages. Renaming it in Zigbee2MQTT is fine.</p>
        <label>Zigbee2MQTT device <select data-z2m><option value="">Choose…</option>${all.filter(fits).map(option).join("")}${
          all.some((dv) => !fits(dv)) ? `<optgroup label="Other devices">${all.filter((dv) => !fits(dv)).map(option).join("")}</optgroup>` : ""
        }</select></label>`;
    } else if (m) {
      const ents = Object.values(this._hass.entities || {});
      const devices = Object.values(this._hass.devices || {})
        .filter((dv) => ents.some((en) => en.device_id === dv.id && en.entity_id.startsWith("event.")))
        .sort((a, b) => (a.name_by_user || a.name || "").localeCompare(b.name_by_user || b.name || ""));
      const events = this._entities(["event"]);
      inputs = `<h3>Where its presses come from</h3>
        <select data-device><option value="">Fill in from a device…</option>${devices
          .map((dv) => `<option value="${esc(dv.id)}">${esc(dv.name_by_user || dv.name)}</option>`)
          .join("")}</select>
        ${m.slots
          .map(
            (sl) => `<label>${esc(sl.name)} <select data-slot="${esc(sl.slot)}"><option value="">Choose…</option>${events
              .map((id) => `<option value="${esc(id)}" ${f.entities?.[sl.slot] === id ? "selected" : ""}>${esc(this._name(id))} (${esc(id)})</option>`)
              .join("")}</select></label>`
          )
          .join("")}`;
    }
    const existing = !!f.id;
    const importer =
      existing && m?.input === "knx"
        ? `<h3>Copy from an old automation</h3>
          <p class="muted small">Reads a "choose by trigger id" automation for this plate's addresses. Simple actions become menu choices. Fixed gestures are skipped. The old automation is left as it is.</p>
          <div class="row"><select data-import><option value="">Choose an automation…</option>${this._entities(["automation"])
            .map((a) => `<option value="${esc(a)}">${esc(this._name(a))}</option>`)
            .join("")}</select><button data-act="import">Copy</button></div>`
        : "";
    return `<div class="backdrop" data-act="close-form"></div>
      <div class="dialog wide" role="dialog" aria-label="Switch">
        <header><b>${existing ? esc(f.name) : "Add a switch"}</b><button class="icon" data-act="close-form" aria-label="Close">✕</button></header>
        <div class="grid2">
          <label>Name <input data-form="name" value="${esc(f.name || "")}"></label>
          <label>Room <select data-form="area_id"><option value="">No room</option>${areas}</select></label>
          <label>Model <select data-form="model"><option value="">Choose…</option>${models}</select></label>
          ${existing ? "" : `<p class="muted small">A new switch starts in a dry run: presses are logged and nothing runs.</p>`}
        </div>
        ${inputs}
        ${m ? this._renderPutBackForm(f, m) : ""}
        ${f.error ? `<p class="error">${esc(f.error)}</p>` : ""}
        <div class="row end">
          ${existing ? `<button class="danger" data-act="delete-switch">Delete</button>` : ""}
          <button data-act="close-form">Cancel</button>
          <button class="primary" data-act="save-switch">Save</button>
        </div>
        ${importer}
        ${f.notes ? `<ul class="small">${f.notes.map((n) => `<li>${esc(n)}</li>`).join("")}</ul>` : ""}
        ${existing ? `<h3>The way out</h3><div class="row"><button data-act="export">Show as a plain automation</button></div>` : ""}
        ${f.exported ? `<textarea rows="12" readonly spellcheck="false">${esc(JSON.stringify(f.exported, null, 2))}</textarea>` : ""}
      </div>`;
  }

  _renderLog() {
    const log = (this._data.log || []).slice().reverse();
    if (!log.length) return `<p class="muted">Nothing pressed yet.</p>`;
    const name = (id) => this._switch(id)?.name || id;
    const rows = log
      .map((e) => {
        const b = this._switch(e.switch)?.bindings?.[e.control]?.[e.gesture];
        const what = ["fixed", "error", "put back"].includes(e.result) ? e.detail : b ? this._describe(b) : "";
        return `<tr class="r-${esc(e.result.replace(" ", "-"))}">
          <td>${esc(time(e.at))}</td><td>${esc(name(e.switch))}</td><td>${esc(e.control_name)}</td>
          <td>${esc(e.gesture_name)}${e.steps > 1 ? ` ×${e.steps}` : ""}</td>
          <td>${esc(RESULT[e.result] || e.result)}${what ? `: ${esc(what)}` : ""}${e.source === "test" ? ` <span class="muted">(test)</span>` : ""}</td></tr>`;
      })
      .join("");
    return `<table class="log"><tr><th>When</th><th>Switch</th><th>Button</th><th>Gesture</th><th>What happened</th></tr>${rows}</table>`;
  }

  // ---- events ---------------------------------------------------------------------------

  async _click(ev) {
    const t = ev.target.closest("[data-act],[data-tab]");
    if (!t) return;
    if (t.dataset.tab) {
      this._tab = t.dataset.tab;
      this._render();
      return;
    }
    const act = t.dataset.act;
    try {
      if (act === "control") {
        this._sheet = { switch: t.dataset.switch, control: t.dataset.control };
        this._want = null;
      }
      else if (act === "close-sheet") this._sheet = null;
      else if (act === "close-editor") this._edit = null;
      else if (act === "close-form") this._form = null;
      else if (act === "edit-binding") this._openEditor(t.dataset.gesture);
      else if (act === "clear-binding") await this._setBinding(t.dataset.gesture, null);
      else if (act === "test")
        await this._ws({ type: "button_blueprinter/test", switch: this._sheet.switch, control: this._sheet.control, gesture: t.dataset.gesture });
      else if (act === "fix") await this._toggleFixed(t.dataset.gesture);
      else if (act === "save-looks") await this._saveLooks();
      else if (act === "save-led") await this._saveLed();
      else if (act === "ask-look") await this._askLook();
      else if (act === "withdraw-look") {
        if (confirm("Withdraw this request?"))
          await this._ws({ type: "button_blueprinter/request_look", switch: t.dataset.switch, control: t.dataset.control, look: null });
        this._want = null;
      } else if (act === "mark-in-ets") {
        await this._ws({ type: "button_blueprinter/mark_in_ets", switch: t.dataset.switch, control: t.dataset.control, in_ets: t.dataset.on === "1" });
      } else if (act === "finish-in-ets") {
        if (confirm(`Has this plate been downloaded? The ${t.dataset.count} buttons marked “In ETS” become how they look here.`))
          await this._ws({ type: "button_blueprinter/finish_in_ets", switch: t.dataset.switch });
      } else if (act === "finish-look") {
        if (confirm("Is the plate showing this now? It becomes how the button looks here."))
          await this._ws({ type: "button_blueprinter/finish_request", switch: t.dataset.switch, control: t.dataset.control });
        this._want = null;
      }
      else if (act === "unpick") {
        const field = t.dataset.field;
        this._edit.values[field] = (this._edit.values[field] || []).filter((id) => id !== t.dataset.id);
      } else if (act === "save-binding") await this._saveBinding();
      else if (act === "new-switch") this._form = { model: "", name: "", area_id: "", knx: {}, entities: {} };
      else if (act === "edit-switch") this._form = JSON.parse(JSON.stringify(this._switch(t.dataset.switch)));
      else if (act === "save-switch") await this._saveSwitch();
      else if (act === "put-back") await this._ws({ type: "button_blueprinter/put_back", switch: t.dataset.switch });
      else if (act === "delete-switch") {
        if (confirm(`Delete ${this._form.name}? Its buttons stop doing anything through Button Blueprinter.`)) {
          await this._ws({ type: "button_blueprinter/delete_switch", switch: this._form.id });
          this._form = null;
        }
      } else if (act === "import") {
        const auto = this.shadowRoot.querySelector("[data-import]")?.value;
        if (auto) {
          const r = await this._ws({ type: "button_blueprinter/import", switch: this._form.id, automation: auto });
          this._form = { ...JSON.parse(JSON.stringify(this._switch(this._form.id))), notes: r.notes };
        }
      } else if (act === "export") {
        const r = await this._ws({ type: "button_blueprinter/export", switch: this._form.id });
        this._form.exported = r.automation;
      }
    } catch (err) {
      const msg = err?.message || String(err);
      if (this._edit) this._edit.error = msg;
      else if (this._form) this._form.error = msg;
      else alert(msg);
    }
    this._render();
  }

  _wantChanged(t) {
    if (!this._want || t.dataset.want === undefined) return false;
    this._want.look = { ...this._want.look, [t.dataset.want]: t.value };
    this._want.note = "";
    const s = this._switch(this._want.switch);
    const m = s && this._model(s.model);
    const box = this.shadowRoot.querySelector(".wantpreview");
    if (m && box) box.innerHTML = this._lookPreview(m, this._want.look);
    return true;
  }

  _change(ev) {
    const t = ev.target;
    if (this._wantChanged(t)) return;
    if (t.dataset.mode) {
      this._ws({ type: "button_blueprinter/set_mode", switch: t.dataset.mode, mode: t.value }).catch((e) => alert(e.message));
      return;
    }
    if (this._edit) {
      if (t.dataset.kind !== undefined) {
        this._edit.kind = t.value;
        this._edit.values = {};
        this._edit.error = null;
      } else if (t.dataset.pick) {
        if (t.value) this._edit.values[t.dataset.pick] = [...(this._edit.values[t.dataset.pick] || []), t.value];
      } else if (t.dataset.val) this._edit.values[t.dataset.val] = t.value;
      else if (t.dataset.bool) this._edit.values[t.dataset.bool] = t.checked;
      this._render();
      return;
    }
    if (!this._form) return;
    if (t.dataset.pbOn !== undefined) {
      this._form.put_back = t.checked ? { minutes: 30 } : null;
      this._render();
      return;
    }
    if (t.dataset.pb) {
      const minutes = parseInt(t.value, 10);
      if (minutes > 0) this._form.put_back = { ...(this._form.put_back || {}), minutes };
      return;
    }
    if (t.dataset.pbControl) {
      const pb = this._form.put_back || {};
      const set = new Set(pb.controls || []);
      if (t.checked) set.add(t.dataset.pbControl);
      else set.delete(t.dataset.pbControl);
      this._form.put_back = { ...pb, controls: [...set] };
      return;
    }
    if (t.dataset.form) {
      this._form[t.dataset.form] = t.value;
      if (t.dataset.form === "model") {
        this._form.knx = {};
        this._form.entities = {};
        this._form.device = null;
      }
      this._render();
    } else if (t.dataset.z2m !== undefined) {
      this._form.device = t.value || null;
      const dv = (this._data.z2m_devices || []).find((x) => x.id === t.value);
      if (dv && !this._form.name) this._form.name = dv.name;
      if (dv?.area_id && !this._form.area_id) this._form.area_id = dv.area_id;
      this._render();
    } else if (t.dataset.slot) {
      this._form.entities = { ...(this._form.entities || {}), [t.dataset.slot]: t.value };
      if (!t.value) delete this._form.entities[t.dataset.slot];
    } else if (t.dataset.device !== undefined && t.value && this._form.model) {
      const device = t.value;
      this._ws({ type: "button_blueprinter/suggest", model: this._form.model, device })
        .then((r) => {
          this._form.entities = { ...(this._form.entities || {}), ...r.entities };
          const dv = this._hass.devices?.[device];
          if (!this._form.name && dv) this._form.name = dv.name_by_user || dv.name;
          if (!this._form.area_id && dv?.area_id) this._form.area_id = dv.area_id;
          this._render();
        })
        .catch((e) => {
          this._form.error = e.message;
          this._render();
        });
    }
  }

  _input(ev) {
    const t = ev.target;
    if (this._wantChanged(t)) return;
    if (this._edit && t.dataset.json !== undefined) this._edit.json = t.value;
    else if (this._edit && t.dataset.val) this._edit.values[t.dataset.val] = t.value;
    else if (this._form && t.dataset.form) this._form[t.dataset.form] = t.value;
    else if (this._form && t.dataset.knx) this._form.knx = { ...(this._form.knx || {}), [t.dataset.knx]: t.value.trim() };
  }

  _openEditor(gesture) {
    const s = this._switch(this._sheet.switch);
    const b = s.bindings?.[this._sheet.control]?.[gesture];
    const values = b?.menu ? { ...b.menu } : {};
    delete values.kind;
    this._edit = {
      gesture,
      kind: b?.actions ? "__actions" : b?.menu?.kind || "",
      values,
      json: b?.actions ? JSON.stringify(b.actions, null, 2) : "[\n  \n]",
      error: null,
    };
  }

  _setBinding(gesture, binding) {
    return this._ws({
      type: "button_blueprinter/set_binding",
      switch: this._sheet.switch,
      control: this._sheet.control,
      gesture,
      binding,
    });
  }

  async _saveBinding() {
    const e = this._edit;
    let binding;
    if (e.kind === "__actions") {
      let actions;
      try {
        actions = JSON.parse(e.json);
      } catch (err) {
        throw new Error(`That isn't valid JSON: ${err.message}`);
      }
      binding = { actions: Array.isArray(actions) ? actions : [actions] };
    } else {
      const values = {};
      for (const [k, v] of Object.entries(e.values)) if (v !== "" && v !== undefined && v !== null) values[k] = v;
      binding = { menu: { kind: e.kind, ...values } };
    }
    await this._setBinding(e.gesture, binding);
    this._edit = null;
  }

  async _toggleFixed(gesture) {
    const s = this._switch(this._sheet.switch);
    const fixed = JSON.parse(JSON.stringify(s.fixed || {}));
    const c = this._sheet.control;
    if (fixed[c]?.[gesture]) {
      delete fixed[c][gesture];
      if (!Object.keys(fixed[c]).length) delete fixed[c];
    } else {
      const text = prompt("What does it do, outside Home Assistant? (e.g. Room lights on, KNX)");
      if (!text) return;
      fixed[c] = { ...(fixed[c] || {}), [gesture]: text };
    }
    await this._ws({ type: "button_blueprinter/save_switch", switch: { id: s.id, fixed } });
  }

  async _saveLooks() {
    const s = this._switch(this._sheet.switch);
    const c = this._sheet.control;
    const looks = JSON.parse(JSON.stringify(s.looks || {}));
    looks[c] = {};
    for (const el of this.shadowRoot.querySelectorAll("[data-look]")) {
      const v = el.value.trim();
      if (v) looks[c][el.dataset.look] = v;
    }
    if (!Object.keys(looks[c]).length) delete looks[c];
    await this._ws({ type: "button_blueprinter/save_switch", switch: { id: s.id, looks } });
  }

  async _saveLed() {
    const s = this._switch(this._sheet.switch);
    const c = this._sheet.control;
    const val = (sel) => this.shadowRoot.querySelector(sel)?.value?.trim() || "";
    const leds = JSON.parse(JSON.stringify(s.leds || {}));
    const entity = val('[data-led="entity_id"]');
    if (entity) leds[c] = { entity_id: entity, state: val('[data-led="state"]') || "on" };
    else delete leds[c];
    await this._ws({ type: "button_blueprinter/save_switch", switch: { id: s.id, leds } });
  }

  async _askLook() {
    const w = this._want;
    if (!w) return;
    const look = Object.fromEntries(Object.entries(w.look).filter(([, v]) => v !== "" && v != null));
    const r = await this._ws({ type: "button_blueprinter/request_look", switch: w.switch, control: w.control, look });
    w.note = r?.result === "already" ? "The plate shows that already, so nothing is waiting." : "Asked. It's on the “Waiting for ETS” list.";
    this._render();
  }

  async _saveSwitch() {
    const f = this._form;
    const m = this._model(f.model);
    if (!m) throw new Error("Choose a model");
    const change = { name: f.name, model: f.model, area_id: f.area_id || null };
    change.put_back = f.put_back?.minutes ? { minutes: f.put_back.minutes, ...(f.put_back.controls?.length ? { controls: f.put_back.controls } : {}) } : null;
    if (f.id) change.id = f.id;
    if (m.input === "knx") change.knx = Object.fromEntries(Object.entries(f.knx || {}).filter(([, v]) => v));
    else if (m.input === "zigbee2mqtt") change.device = f.device || null;
    else change.entities = f.entities || {};
    await this._ws({ type: "button_blueprinter/save_switch", switch: change });
    this._form = null;
  }
}

const STYLE = `
  :host { display:block; background:var(--primary-background-color); color:var(--primary-text-color); min-height:100vh; font-family:var(--paper-font-body1_-_font-family, system-ui, sans-serif); }
  .top { display:flex; flex-wrap:wrap; align-items:center; justify-content:space-between; gap:8px; padding:16px; border-bottom:1px solid var(--divider-color); background:var(--app-header-background-color, var(--card-background-color)); color:var(--app-header-text-color, inherit); }
  h1 { font-size:20px; margin:0; font-weight:500; }
  h2 { font-size:16px; margin:24px 0 8px; font-weight:500; }
  h3 { font-size:14px; margin:16px 0 6px; font-weight:500; }
  nav { display:flex; gap:6px; flex-wrap:wrap; }
  main { padding:8px 16px 48px; max-width:1200px; }
  button { font:inherit; cursor:pointer; border-radius:8px; border:1px solid var(--divider-color); background:var(--card-background-color); color:var(--primary-text-color); padding:6px 12px; }
  button.primary { background:var(--primary-color); color:var(--text-primary-color, #fff); border-color:var(--primary-color); }
  button.danger { color:var(--error-color); }
  button.tab.on { border-color:var(--primary-color); color:var(--primary-color); }
  button.icon { border:none; background:none; padding:4px 8px; font-size:16px; }
  button[disabled] { opacity:.5; cursor:default; }
  .muted { color:var(--secondary-text-color); }
  .small { font-size:12px; }
  .error { color:var(--error-color); }
  .warn { color:var(--warning-color, #b26a00); }
  .row { display:flex; gap:8px; align-items:center; flex-wrap:wrap; }
  .row.end { justify-content:flex-end; margin-top:12px; }
  .switches { display:grid; grid-template-columns:repeat(auto-fill, minmax(260px, 1fr)); gap:12px; }
  .card { background:var(--card-background-color); border-radius:12px; padding:12px; box-shadow:var(--ha-card-box-shadow, 0 1px 2px rgba(0,0,0,.15)); display:flex; flex-direction:column; gap:10px; }
  .card header { display:flex; justify-content:space-between; gap:8px; align-items:flex-start; }
  .card header .row { flex-wrap:nowrap; }
  .pill { white-space:nowrap; font-size:12px; padding:2px 8px; border-radius:10px; background:var(--secondary-background-color); }
  .pill.mode-live { background:var(--success-color, #2e7d32); color:#fff; }
  .pill.mode-dry_run { background:var(--warning-color, #b26a00); color:#fff; }
  .plate { position:relative; margin:4px auto; box-shadow:inset 0 0 0 1px rgba(0,0,0,.25), 0 2px 6px rgba(0,0,0,.2); }
  .decor { position:absolute; border:2px solid; opacity:.35; pointer-events:none; box-sizing:border-box; }
  .decor.round { border-radius:50%; }
  .ctl { position:absolute; box-sizing:border-box; padding:0; display:flex; flex-direction:column; align-items:center; justify-content:center; gap:1px; border:1px solid rgba(127,127,127,.45); background:rgba(255,255,255,.06); font-size:11px; line-height:1.1; overflow:hidden; border-radius:4px; }
  .ctl.circle { border-radius:50%; }
  .ctl.ring { border-radius:50%; background:rgba(127,127,127,.22); }
  .ctl .ringlabel { position:absolute; top:3%; font-size:10px; }
  .ctl.bound { box-shadow:inset 0 0 0 2px var(--primary-color); }
  .ctl.fixed { background-image:repeating-linear-gradient(45deg, rgba(127,127,127,.3) 0 4px, transparent 4px 8px); }
  .ctl.flash { background-color:var(--primary-color); color:#fff !important; }
  .ctl ha-icon { --mdc-icon-size:16px; }
  .ctl:hover { filter:brightness(1.2); }
  .plate.dynamic .screen { position:absolute; left:19%; right:19%; top:6%; bottom:6%; background:#111214; border-radius:3px; box-shadow:inset 0 0 0 1px #000; }
  .plate.dynamic .edge { position:absolute; top:6%; bottom:6%; width:13%; background:rgba(255,255,255,.05); border-radius:2px; }
  .plate.dynamic .edge.left { left:4%; }
  .plate.dynamic .edge.right { right:4%; }
  .ctl.onscreen { background:transparent; border-color:rgba(255,255,255,.08); }
  .ctl.onscreen.bound { box-shadow:inset 0 0 0 1px var(--primary-color); }
  .sicon { display:inline-block; width:22px; height:22px; }
  .sicon.disp, ha-icon.disp { width:20px; height:20px; --mdc-icon-size:20px; }
  .sicon.insert, ha-icon.insert { width:26px; height:26px; --mdc-icon-size:26px; }
  .disptext { font-size:8px; line-height:1; white-space:nowrap; }
  .ctl .note { font-size:9px; opacity:.7; }
  .preview { display:flex; gap:12px; margin-top:8px; font-size:12px; color:var(--secondary-text-color); }
  .pv { display:flex; flex-direction:column; align-items:center; gap:3px; }
  .pvscreen { background:#111214; border-radius:6px; padding:8px 12px; display:flex; flex-direction:column; align-items:center; gap:3px; min-width:56px; min-height:24px; }
  .led { position:absolute; top:3px; right:3px; width:6px; height:6px; border-radius:50%; background:#4caf50; box-shadow:0 0 4px #4caf50; }
  .backdrop { position:fixed; inset:0; background:rgba(0,0,0,.35); z-index:10; }
  .backdrop.top2 { z-index:20; }
  .sheet, .dialog { position:fixed; z-index:11; background:var(--card-background-color); border-radius:12px; padding:16px; box-shadow:0 8px 32px rgba(0,0,0,.35); max-height:85vh; overflow:auto; box-sizing:border-box; }
  .sheet { right:16px; top:72px; width:min(580px, calc(100vw - 32px)); }
  .dialog { left:50%; top:50%; transform:translate(-50%,-50%); width:min(460px, calc(100vw - 32px)); z-index:21; display:flex; flex-direction:column; gap:8px; }
  .dialog.wide { width:min(640px, calc(100vw - 32px)); z-index:11; }
  .sheet header, .dialog header { display:flex; justify-content:space-between; align-items:center; margin-bottom:6px; gap:8px; }
  table.gestures { width:100%; border-collapse:collapse; }
  table.gestures th { text-align:left; font-weight:500; white-space:nowrap; padding:6px 8px 6px 0; vertical-align:top; }
  table.gestures td { padding:6px 4px; vertical-align:top; border-top:1px solid var(--divider-color); }
  td.acts { white-space:nowrap; text-align:right; }
  td.acts button { padding:3px 8px; font-size:12px; }
  .fixedtext { color:var(--secondary-text-color); font-style:italic; }
  label { display:flex; flex-direction:column; gap:3px; font-size:13px; }
  label.check { flex-direction:row; align-items:center; gap:6px; }
  input, select, textarea { font:inherit; padding:6px 8px; border-radius:6px; border:1px solid var(--divider-color); background:var(--primary-background-color); color:var(--primary-text-color); }
  textarea { font-family:monospace; font-size:12px; width:100%; box-sizing:border-box; }
  .grid2 { display:grid; grid-template-columns:1fr 1fr; gap:8px; }
  @media (max-width:520px) { .grid2 { grid-template-columns:1fr; } .sheet { left:8px; right:8px; width:auto; } td.acts { white-space:normal; } }
  .field { display:flex; flex-direction:column; gap:4px; font-size:13px; }
  .chips { display:flex; flex-wrap:wrap; gap:4px; }
  .chip { background:var(--secondary-background-color); border-radius:12px; padding:2px 4px 2px 10px; display:inline-flex; align-items:center; gap:2px; }
  .chip .x { border:none; background:none; padding:0 4px; font-size:11px; }
  table.log { width:100%; border-collapse:collapse; font-size:13px; margin-top:12px; }
  table.log th, table.log td { text-align:left; padding:6px; border-bottom:1px solid var(--divider-color); }
  tr.r-error td { color:var(--error-color); }
  tr.r-would-run td:last-child { color:var(--warning-color, #b26a00); }
  code { font-size:12px; }
  .wait { position:absolute; bottom:3px; right:3px; width:7px; height:7px; border-radius:50%; background:#ff9f43; box-shadow:0 0 0 2px rgba(0,0,0,.35); }
  .ctl.waiting { outline:2px dashed #ff9f43; outline-offset:1px; }
  .lookrow { display:flex; align-items:center; gap:10px; flex-wrap:wrap; margin:6px 0; }
  .lookrow .preview { margin-top:0; }
  .rowlabel { min-width:64px; }
  .pvinsert { width:40px; height:40px; border-radius:6px; display:flex; align-items:center; justify-content:center; }
  .waitbox { border:1px solid #ff9f43; border-radius:10px; padding:10px 12px; margin:8px 0; display:flex; flex-direction:column; gap:4px; }
  .waitlist { display:grid; grid-template-columns:repeat(auto-fill, minmax(280px, 1fr)); gap:12px; }
  .waitcard { border:1px solid var(--divider-color); border-radius:10px; padding:10px 12px; display:flex; flex-direction:column; gap:4px; background:var(--card-background-color); }
  .waitcard.in-ets { border-color:#4aa3ff; background:color-mix(in srgb, #4aa3ff 8%, var(--card-background-color)); }
  .pill.in-ets { background:#4aa3ff; color:#fff; margin-left:6px; font-weight:400; }
  .inets-bar { justify-content:space-between; border:1px solid #4aa3ff; border-radius:10px; padding:6px 10px; margin:0 0 10px; }
  .waitcard header { display:flex; gap:8px; align-items:baseline; flex-wrap:wrap; }
  table.changes { border-collapse:collapse; font-size:12px; width:100%; }
  table.changes th, table.changes td { text-align:left; padding:3px 6px 3px 0; border-bottom:1px solid var(--divider-color); }
`;

if (!customElements.get("button-blueprinter-panel")) customElements.define("button-blueprinter-panel", ButtonBlueprinterPanel);
