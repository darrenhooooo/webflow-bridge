// Webflow Bridge for Firefox -- P2 accessibility-like snapshot generator.
//
// Injected into the page MAIN world through script.evaluate by the daemon
// (ff/daemon/ff_bridge.py).  __START__ and __LIMIT__ are integer
// placeholders replaced by the daemon at injection time (start = first
// emitted node's FULL-list index, limit = max nodes returned on this page).
//
// Semantics mirror the Chrome edition's snapshotExpression() in
// extension/background.js (the canonical contract):
//   - querySelectorAll over a composite control selector (fast prefilter)
//   - per-element visibility + allowed-type filtering
//   - role/name/text extraction, with the empty-control name fallback
//     placeholder -> aria-label -> title -> id
//   - a CSS nth-of-type path up to document.body, capped at 40 segments
//     (truncated from the ROOT side when deeper)
//   - empty-text skip applies to NON-control containers only; controls
//     (empty inputs / contenteditable editors are fill targets) are always
//     kept
//   - refs are FULL-list indices "@e0", "@e1", ... so nodes stay stable
//     across start>0 pagination
//   - every element is guarded so a mid-walk change skips it instead of
//     failing the whole snapshot
//   - runs in the main frame only (script.evaluate without a nested realm)
//
// Returns {url, title, total, start, nodes:[{ref,tag,role,name,text,path}]}
// or {error: "snapshot failed: ..."}.
(() => {
  const START = __START__;
  const LIMIT = __LIMIT__;
  const ROLE_OK = new Set(["button", "link", "textbox", "combobox", "checkbox", "radio", "menuitem", "tab", "option"]);
  const SEL = 'a[href],button,input:not([type="hidden"]),textarea,select,[contenteditable],[role],[summary],img[alt]';
  function isVisible(el) {
    // Visible rule: laid out (offsetParent) or painted (has rects) -- covers
    // position:fixed whose offsetParent is null.
    if (el.offsetParent === null) {
      if (!el.getClientRects || el.getClientRects().length === 0) return false;
    }
    return true;
  }
  function isAllowed(el) {
    const tag = el.tagName;
    if (tag === "A") return el.hasAttribute("href");
    if (tag === "BUTTON" || tag === "SUMMARY" || tag === "TEXTAREA" || tag === "SELECT") return true;
    if (tag === "INPUT") return (el.type || "text").toLowerCase() !== "hidden";
    if (tag === "IMG") {
      const alt = el.getAttribute("alt");
      return typeof alt === "string" && alt.trim() !== "";
    }
    const ce = el.getAttribute("contenteditable");
    if (ce === "" || ce === "true" || ce === "plaintext-only") return true;
    const role = el.getAttribute("role");
    return !!(role && ROLE_OK.has(String(role).toLowerCase()));
  }
  // Control types an agent interacts with: form controls, contenteditable
  // editors, and interactive roles.  Controls are ALWAYS kept in the
  // snapshot even when their text/name is empty -- an empty input / empty
  // contenteditable is exactly the element an agent needs to fill.
  function isControl(el) {
    const tag = el.tagName;
    if (tag === "INPUT") return (el.type || "text").toLowerCase() !== "hidden";
    if (tag === "TEXTAREA" || tag === "SELECT") return true;
    const ce = el.getAttribute && el.getAttribute("contenteditable");
    if (ce === "" || ce === "true" || ce === "plaintext-only") return true;
    const role = el.getAttribute("role");
    if (role) return ROLE_OK.has(String(role).toLowerCase());
    return false;
  }
  function roleOf(el) {
    const r = el.getAttribute("role");
    if (r) return String(r).toLowerCase();
    const tag = el.tagName;
    if (tag === "A") return "link";
    if (tag === "BUTTON") return "button";
    if (tag === "TEXTAREA") return "textbox";
    if (tag === "SELECT") return "combobox";
    if (tag === "INPUT") {
      const ty = (el.type || "text").toLowerCase();
      if (ty === "checkbox") return "checkbox";
      if (ty === "radio") return "radio";
      if (ty === "button" || ty === "submit" || ty === "reset" || ty === "image") return "button";
      return "textbox";
    }
    return "";
  }
  function nameOf(el, text) {
    // A control with empty text is a "fill me" target -- never leave its
    // name empty: placeholder -> aria-label -> title -> id.
    if (isControl(el) && !text) {
      const ph = el.getAttribute && el.getAttribute("placeholder");
      if (ph && String(ph).trim()) return ph;
      const al = el.getAttribute("aria-label");
      if (al && String(al).trim()) return al;
      const ti = el.getAttribute("title");
      if (ti && String(ti).trim()) return ti;
      const id = el.id;
      if (typeof id === "string" && id.trim()) return id;
      return "";
    }
    const al = el.getAttribute("aria-label");
    if (al && String(al).trim()) return al;
    const ti = el.getAttribute("title");
    if (ti && String(ti).trim()) return ti;
    if (el.tagName === "IMG") {
      const alt = el.getAttribute("alt");
      if (alt) return alt;
    }
    return "";
  }
  function textOf(el) {
    const tag = el.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA") {
      const ty = (el.type || "text").toLowerCase();
      if (ty === "checkbox" || ty === "radio") return "";   // label, not "on"
      const v = el.value;
      return typeof v === "string" ? v.trim().slice(0, 120) : "";
    }
    const t = (el.innerText || "").replace(/\s+/g, " ").trim();
    return t.slice(0, 120);
  }
  function cssPath(el) {
    const parts = [];
    let cur = el;
    while (cur && cur.parentElement && cur !== document.body) {
      const parent = cur.parentElement;
      let nth = 1;
      for (let s = cur.previousElementSibling; s; s = s.previousElementSibling) {
        if (s.tagName === cur.tagName) nth += 1;
      }
      parts.push(cur.tagName.toLowerCase() + ":nth-of-type(" + nth + ")");
      cur = parent;
    }
    parts.reverse();
    if (parts.length > 40) parts.splice(0, parts.length - 40);
    return parts.join(" > ");
  }
  let els;
  try {
    els = document.querySelectorAll(SEL);
  } catch (err) {
    return { error: "snapshot failed: " + String((err && err.message) || err) };
  }
  const out = [];
  let total = 0;
  for (let i = 0; i < els.length; i += 1) {
    const el = els[i];
    try {
      if (!isVisible(el) || !isAllowed(el)) continue;
      const path = cssPath(el);
      const text = textOf(el);
      const name = nameOf(el, text);
      const role = roleOf(el);
      // Empty-text skip applies to NON-control containers only; controls
      // are always kept (empty inputs / contenteditable editors are fill
      // targets).
      if (!isControl(el) && !name && !text && !role) continue;
      total += 1;
      if (total <= START) continue;                // element before this page
      if (out.length >= LIMIT) continue;           // page full; keep counting total
      out.push({
        ref: "@e" + (total - 1),   // FULL-list index -- stable across pages
        tag: el.tagName.toLowerCase(),
        role: role,
        name: name,
        text: text,
        path: path,
      });
    } catch (err) { /* element changed mid-walk (detached) -- skip it */ }
  }
  return { url: location.href, title: document.title, total: total,
           start: START, nodes: out };
})()
