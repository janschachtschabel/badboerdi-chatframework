/**
 * Material Symbols als Inline-SVG.
 *
 * Quelle: Google Material Symbols (Outlined Variant), 24px-Grid,
 * stroke=none, fill=currentColor — damit der CSS-Color des Buttons
 * automatisch das Icon einfärbt.
 *
 * Warum Inline-SVG statt Material-Icons-Font?
 *   - Web-Fonts laden im Shadow-DOM unzuverlässig (Browser-spezifische
 *     Quirks beim @font-face innerhalb shadow-roots).
 *   - Inline-SVG kostet pro Icon ~200-400 Bytes — bei diesem Set
 *     wenige KB im Bundle, kein zusätzlicher HTTP-Request.
 *   - Komplett offline-fähig, kein CDN-Dependency.
 *
 * width/height = "1em": die Icons skalieren automatisch mit der
 * Schriftgröße des umgebenden Elements (font-size) — kein zusätz-
 * liches CSS-Sizing nötig. CSS-Overrides via "width: 20px" greifen
 * trotzdem (CSS gewinnt gegen SVG-Presentation-Attribute).
 *
 * Wenn weitere Icons gebraucht werden: aus Material-Symbols-Library
 * laden (`https://fonts.google.com/icons`), in dieser Datei als String-
 * Konstante ergänzen, im Template verwenden:
 *
 *   <span [innerHTML]="ICONS.close | safeSvg"></span>
 *
 * Bitte NIEMALS direkt mit `[innerHTML]="ICONS.close"` ohne `| safeSvg`
 * verwenden — Angular's Default-Sanitizer strippt `xmlns` und `viewBox`
 * und macht das SVG kaputt.
 */
export const ICONS = {
  // ── Header / Chat-Aktionen ─────────────────────────────────────────
  /** Sprachausgabe an */
  volume_up: `<svg xmlns="http://www.w3.org/2000/svg" height="1em" viewBox="0 -960 960 960" width="1em" fill="currentColor"><path d="M560-131v-82q90-26 145-100t55-168q0-94-55-168T560-749v-82q124 28 202 125.5T840-481q0 127-78 224.5T560-131ZM120-360v-240h160l200-200v640L280-360H120Zm440 40v-322q47 22 73.5 66t26.5 96q0 51-26.5 94.5T560-320Z"/></svg>`,
  /** Sprachausgabe aus */
  volume_off: `<svg xmlns="http://www.w3.org/2000/svg" height="1em" viewBox="0 -960 960 960" width="1em" fill="currentColor"><path d="M792-56 671-177q-25 16-53 27.5T560-131v-82q14-5 27.5-10t25.5-12L480-368v208L280-360H120v-240h128L56-792l56-56 736 736-56 56Zm-8-232-58-58q17-31 25.5-65t8.5-70q0-94-55-168T560-749v-82q124 28 202 125.5T840-481q0 53-14.5 102T784-288ZM650-422l-90-90v-130q47 22 73.5 66t26.5 96q0 15-2.5 29.5T650-422ZM480-592 376-696l104-104v208Z"/></svg>`,
  /** Mikrofon */
  mic: `<svg xmlns="http://www.w3.org/2000/svg" height="1em" viewBox="0 -960 960 960" width="1em" fill="currentColor"><path d="M480-400q-50 0-85-35t-35-85v-240q0-50 35-85t85-35q50 0 85 35t35 85v240q0 50-35 85t-85 35Zm0-240Zm-40 520v-123q-104-14-172-93t-68-184h80q0 83 58.5 141.5T480-320q83 0 141.5-58.5T680-520h80q0 105-68 184t-172 93v123h-80Zm40-360q17 0 28.5-11.5T520-520v-240q0-17-11.5-28.5T480-800q-17 0-28.5 11.5T440-760v240q0 17 11.5 28.5T480-480Z"/></svg>`,
  /** Mikrofon aus */
  mic_off: `<svg xmlns="http://www.w3.org/2000/svg" height="1em" viewBox="0 -960 960 960" width="1em" fill="currentColor"><path d="M710-362 594-478q4-9 5-21.5t1-20.5v-240q0-50-35-85t-85-35q-50 0-85 35t-35 85v98l-80-80v-18q0-83 58.5-141.5T480-960q83 0 141.5 58.5T680-760v240q0 14-1.5 28t-4.5 26l-44 26v78Zm-230 38q-26 0-46-9.5T398-358l-83-83q-1 0-3 1t-3 1q-83 0-141.5-58.5T160-640h80q0 51 29 94.5t75 65.5l51-50q-26-9-50-31.5T315-624l-50-49v-9q0-50 35-85t85-35q50 0 85 35t35 85v240q0 5-.5 10t-1.5 10l-50-50v-210q0-17-11.5-28.5T414-722q-17 0-28.5 11.5T374-682v60l-77-78q4-69 53-115t130-46q83 0 141.5 58.5T680-661v118l-80-80q-1-32-19-54t-46-29l-55-58v-37q0-17 11.5-28.5T520-840q17 0 28.5 11.5T560-800v109l177 175q4-9 8.5-19.5T752-557l72 71q-14 30-30 55t-37 47l140 140-56 56-89-89q-30 21-61.5 35T620-242l-58-58q34-5 65.5-19t60.5-32l-46-46q-23 15-50 22.5T480-360q-14 0-26-2t-23-7l-72-72q21 9 44.5 12.5T480-422ZM198-78l-56-56 56-56-56 56 56 56Z"/></svg>`,
  /** Debug / Bug */
  bug_report: `<svg xmlns="http://www.w3.org/2000/svg" height="1em" viewBox="0 -960 960 960" width="1em" fill="currentColor"><path d="M480-200q66 0 113-47t47-113v-160q0-66-47-113t-113-47q-66 0-113 47t-47 113v160q0 66 47 113t113 47Zm-80-120h160v-80H400v80Zm0-160h160v-80H400v80Zm80 40Zm0 320q-65 0-120.5-32T272-240H160v-80h84q-3-20-3.5-40t-.5-40h-80v-80h80q0-20 .5-40t3.5-40h-84v-80h112q14-23 31.5-43t40.5-35l-64-66 56-56 86 86q28-9 57-9t57 9l88-86 56 56-66 66q23 15 41.5 34.5T688-640h112v80h-84q3 20 3.5 40t.5 40h80v80h-80q0 20-.5 40t-3.5 40h84v80H688q-32 56-87.5 88T480-120Z"/></svg>`,
  /** Lotsen-Modus (Kompass) */
  explore: `<svg xmlns="http://www.w3.org/2000/svg" height="1em" viewBox="0 -960 960 960" width="1em" fill="currentColor"><path d="m260-260 300-140 140-300-300 140-140 300Zm220-180q-17 0-28.5-11.5T440-480q0-17 11.5-28.5T480-520q17 0 28.5 11.5T520-480q0 17-11.5 28.5T480-440Zm0 360q-83 0-156-31.5T197-197q-54-54-85.5-127T80-480q0-83 31.5-156T197-763q54-54 127-85.5T480-880q83 0 156 31.5T763-763q54 54 85.5 127T880-480q0 83-31.5 156T763-197q-54 54-127 85.5T480-80Zm0-80q134 0 227-93t93-227q0-134-93-227t-227-93q-134 0-227 93t-93 227q0 134 93 227t227 93Zm0-320Z"/></svg>`,
  /** Neu starten / Refresh */
  refresh: `<svg xmlns="http://www.w3.org/2000/svg" height="1em" viewBox="0 -960 960 960" width="1em" fill="currentColor"><path d="M480-160q-134 0-227-93t-93-227q0-134 93-227t227-93q69 0 132 28.5T720-690v-110h80v280H520v-80h168q-32-56-87.5-88T480-720q-100 0-170 70t-70 170q0 100 70 170t170 70q77 0 139-44t87-116h84q-28 106-114 173t-196 67Z"/></svg>`,
  /** Schließen */
  close: `<svg xmlns="http://www.w3.org/2000/svg" height="1em" viewBox="0 -960 960 960" width="1em" fill="currentColor"><path d="m256-200-56-56 224-224-224-224 56-56 224 224 224-224 56 56-224 224 224 224-56 56-224-224-224 224Z"/></svg>`,

  // ── Senden / Stoppen ───────────────────────────────────────────────
  /** Senden (Pfeil) */
  send: `<svg xmlns="http://www.w3.org/2000/svg" height="1em" viewBox="0 -960 960 960" width="1em" fill="currentColor"><path d="M120-160v-640l760 320-760 320Zm80-120 474-200-474-200v140l240 60-240 60v140Zm0 0v-400 400Z"/></svg>`,
  /** Stop (für TTS-active state) */
  stop_circle: `<svg xmlns="http://www.w3.org/2000/svg" height="1em" viewBox="0 -960 960 960" width="1em" fill="currentColor"><path d="M320-320h320v-320H320v320ZM480-80q-83 0-156-31.5T197-197q-54-54-85.5-127T80-480q0-83 31.5-156T197-763q54-54 127-85.5T480-880q83 0 156 31.5T763-763q54 54 85.5 127T880-480q0 83-31.5 156T763-197q-54 54-127 85.5T480-80Zm0-80q134 0 227-93t93-227q0-134-93-227t-227-93q-134 0-227 93t-93 227q0 134 93 227t227 93Zm0-320Z"/></svg>`,

  // ── Navigation / Aktionen ──────────────────────────────────────────
  /** Zurück (Pfeil links) */
  arrow_back: `<svg xmlns="http://www.w3.org/2000/svg" height="1em" viewBox="0 -960 960 960" width="1em" fill="currentColor"><path d="M400-80 0-480l400-400 71 71-329 329 329 329-71 71Z"/></svg>`,
  arrow_forward: `<svg xmlns="http://www.w3.org/2000/svg" height="1em" viewBox="0 -960 960 960" width="1em" fill="currentColor"><path d="M560-80l-71-71 329-329H80v-80h738L489-889l71-71 400 400-400 400Z"/></svg>`,
  /** Chevron rechts (offen, schmaler Pfeil ohne Schaft) — für Karten-CTAs */
  chevron_right: `<svg xmlns="http://www.w3.org/2000/svg" height="1em" viewBox="0 -960 960 960" width="1em" fill="currentColor"><path d="M504-480 320-664l56-56 240 240-240 240-56-56 184-184Z"/></svg>`,
  /** Dropdown-Pfeil */
  arrow_drop_down: `<svg xmlns="http://www.w3.org/2000/svg" height="1em" viewBox="0 -960 960 960" width="1em" fill="currentColor"><path d="M480-360 280-560h400L480-360Z"/></svg>`,
  /** Häkchen (klein) */
  check: `<svg xmlns="http://www.w3.org/2000/svg" height="1em" viewBox="0 -960 960 960" width="1em" fill="currentColor"><path d="M382-240 154-468l57-57 171 171 367-367 57 57-424 424Z"/></svg>`,
  /** Editieren (Stift) */
  edit: `<svg xmlns="http://www.w3.org/2000/svg" height="1em" viewBox="0 -960 960 960" width="1em" fill="currentColor"><path d="M200-200h57l391-391-57-57-391 391v57Zm-80 80v-170l528-527q12-11 26.5-17t30.5-6q16 0 31 6t26 18l55 56q12 11 17.5 26t5.5 30q0 16-5.5 30.5T817-647L290-120H120Zm640-584-56-56 56 56Zm-141 85-28-29 57 57-29-28Z"/></svg>`,
  /** Wiederherstellen (Pfeil-im-Kreis) */
  restore: `<svg xmlns="http://www.w3.org/2000/svg" height="1em" viewBox="0 -960 960 960" width="1em" fill="currentColor"><path d="M440-122q-121-15-200.5-105.5T160-440q0-66 26-126.5T260-672l57 57q-38 34-57.5 79T240-440q0 88 56 155.5T440-202v80Zm80 0v-80q87-16 143.5-83T720-440q0-100-70-170t-170-70h-3l46 46-56 56-144-144 144-144 56 56-46 46h3q134 0 227 93t93 227q0 121-79.5 211.5T520-122Z"/></svg>`,
  /** Drucken */
  print: `<svg xmlns="http://www.w3.org/2000/svg" height="1em" viewBox="0 -960 960 960" width="1em" fill="currentColor"><path d="M640-640v-120H320v120h-80v-200h480v200h-80Zm-480 80h640-640Zm560 100q17 0 28.5-11.5T760-500q0-17-11.5-28.5T720-540q-17 0-28.5 11.5T680-500q0 17 11.5 28.5T720-460Zm-80 260v-160H320v160h320Zm80 80H240v-160H80v-240q0-51 35-85.5t85-34.5h560q51 0 85.5 34.5T880-520v240H720v160Zm80-240v-160q0-17-11.5-28.5T760-560H200q-17 0-28.5 11.5T160-520v160h80v-80h480v80h80Z"/></svg>`,
  /** Download */
  download: `<svg xmlns="http://www.w3.org/2000/svg" height="1em" viewBox="0 -960 960 960" width="1em" fill="currentColor"><path d="M480-320 280-520l56-58 104 104v-326h80v326l104-104 56 58-200 200ZM240-160q-33 0-56.5-23.5T160-240v-120h80v120h480v-120h80v120q0 33-23.5 56.5T720-160H240Z"/></svg>`,
  /** Anschauen / Vorschau (Auge) */
  visibility: `<svg xmlns="http://www.w3.org/2000/svg" height="1em" viewBox="0 -960 960 960" width="1em" fill="currentColor"><path d="M480-320q75 0 127.5-52.5T660-500q0-75-52.5-127.5T480-680q-75 0-127.5 52.5T300-500q0 75 52.5 127.5T480-320Zm0-72q-45 0-76.5-31.5T372-500q0-45 31.5-76.5T480-608q45 0 76.5 31.5T588-500q0 45-31.5 76.5T480-392Zm0 192q-146 0-266-81.5T40-500q54-137 174-218.5T480-800q146 0 266 81.5T920-500q-54 137-174 218.5T480-200Zm0-300Zm0 220q113 0 207.5-59.5T832-500q-50-101-144.5-160.5T480-720q-113 0-207.5 59.5T128-500q50 101 144.5 160.5T480-280Z"/></svg>`,
  /** Senden im Tab / Externer Link */
  open_in_new: `<svg xmlns="http://www.w3.org/2000/svg" height="1em" viewBox="0 -960 960 960" width="1em" fill="currentColor"><path d="M200-120q-33 0-56.5-23.5T120-200v-560q0-33 23.5-56.5T200-840h280v80H200v560h560v-280h80v280q0 33-23.5 56.5T760-120H200Zm188-212-56-56 372-372H560v-80h280v280h-80v-144L388-332Z"/></svg>`,

  // ── Content / Tabs ─────────────────────────────────────────────────
  /** Material / Beschreibung / Notizen */
  description: `<svg xmlns="http://www.w3.org/2000/svg" height="1em" viewBox="0 -960 960 960" width="1em" fill="currentColor"><path d="M320-240h320v-80H320v80Zm0-160h320v-80H320v80ZM240-80q-33 0-56.5-23.5T160-160v-640q0-33 23.5-56.5T240-880h320l240 240v480q0 33-23.5 56.5T720-80H240Zm280-520v-200H240v640h480v-440H520ZM240-800v200-200 640-640Z"/></svg>`,
  /** Suche (Lupe) */
  search: `<svg xmlns="http://www.w3.org/2000/svg" height="1em" viewBox="0 -960 960 960" width="1em" fill="currentColor"><path d="M784-120 532-372q-30 24-69 38t-83 14q-109 0-184.5-75.5T120-580q0-109 75.5-184.5T380-840q109 0 184.5 75.5T640-580q0 44-14 83t-38 69l252 252-56 56ZM380-400q75 0 127.5-52.5T560-580q0-75-52.5-127.5T380-760q-75 0-127.5 52.5T200-580q0 75 52.5 127.5T380-400Z"/></svg>`,
  /** Liste / Inhalte */
  list: `<svg xmlns="http://www.w3.org/2000/svg" height="1em" viewBox="0 -960 960 960" width="1em" fill="currentColor"><path d="M360-200v-80h480v80H360Zm0-240v-80h480v80H360Zm0-240v-80h480v80H360ZM200-160q-33 0-56.5-23.5T120-240q0-33 23.5-56.5T200-320q33 0 56.5 23.5T280-240q0 33-23.5 56.5T200-160Zm0-240q-33 0-56.5-23.5T120-480q0-33 23.5-56.5T200-560q33 0 56.5 23.5T280-480q0 33-23.5 56.5T200-400Zm0-240q-33 0-56.5-23.5T120-720q0-33 23.5-56.5T200-800q33 0 56.5 23.5T280-720q0 33-23.5 56.5T200-640Z"/></svg>`,
  /** Lernpfad / Route */
  route: `<svg xmlns="http://www.w3.org/2000/svg" height="1em" viewBox="0 -960 960 960" width="1em" fill="currentColor"><path d="M280-80q-33 0-56.5-23.5T200-160v-294q-35-13-57.5-43.5T120-568q0-50 35-85t85-35q50 0 85 35t35 85q0 40-22.5 70.5T280-454v294h240v-80q-50 0-85-35t-35-85q0-50 35-85t85-35h80q17 0 28.5-11.5T640-520v-40q-35-13-57.5-43.5T560-680q0-50 35-85t85-35q50 0 85 35t35 85q0 40-22.5 70.5T720-566v46q0 50-35 85t-85 35h-80q-17 0-28.5 11.5T480-360q0 17 11.5 28.5T520-320h160q33 0 56.5 23.5T760-240v80q0 33-23.5 56.5T680-80H280Zm-40-560q17 0 28.5-11.5T280-680q0-17-11.5-28.5T240-720q-17 0-28.5 11.5T200-680q0 17 11.5 28.5T240-640Zm440 0q17 0 28.5-11.5T720-680q0-17-11.5-28.5T680-720q-17 0-28.5 11.5T640-680q0 17 11.5 28.5T680-640ZM240-680Zm440 0Z"/></svg>`,
  /** Chat / Sprechblase */
  chat: `<svg xmlns="http://www.w3.org/2000/svg" height="1em" viewBox="0 -960 960 960" width="1em" fill="currentColor"><path d="M240-400h320v-80H240v80Zm0-120h480v-80H240v80Zm0-120h480v-80H240v80ZM80-80v-720q0-33 23.5-56.5T160-880h640q33 0 56.5 23.5T880-800v480q0 33-23.5 56.5T800-240H240L80-80Zm126-240h594v-480H160v525l46-45Zm-46 0v-480 480Z"/></svg>`,
  /** Webseite / Sprache / Globus */
  language: `<svg xmlns="http://www.w3.org/2000/svg" height="1em" viewBox="0 -960 960 960" width="1em" fill="currentColor"><path d="M480-80q-83 0-156-31.5T197-197q-54-54-85.5-127T80-480q0-83 31.5-156T197-763q54-54 127-85.5T480-880q83 0 156 31.5T763-763q54 54 85.5 127T880-480q0 83-31.5 156T763-197q-54 54-127 85.5T480-80Zm0-82q26-36 45-75t31-83H404q12 44 31 83t45 75Zm-104-16q-18-33-31.5-68.5T322-320H204q29 50 72.5 87t99.5 55Zm208 0q56-18 99.5-55t72.5-87H638q-9 38-22.5 73.5T584-178ZM170-400h136q-3-20-4.5-39.5T300-480q0-21 1.5-40.5T306-560H170q-5 20-7.5 39.5T160-480q0 21 2.5 40.5T170-400Zm216 0h188q3-20 4.5-39.5T580-480q0-21-1.5-40.5T574-560H386q-3 20-4.5 39.5T380-480q0 21 1.5 40.5T386-400Zm268 0h136q5-20 7.5-39.5T800-480q0-21-2.5-40.5T790-560H654q3 20 4.5 39.5T660-480q0 21-1.5 40.5T654-400Zm-16-240h118q-29-50-72.5-87T584-782q18 33 31.5 68.5T638-640Zm-234 0h152q-12-44-31-83t-45-75q-26 36-45 75t-31 83Zm-200 0h118q9-38 22.5-73.5T376-782q-56 18-99.5 55T204-640Z"/></svg>`,
  /** Sammlung / Buch-Stapel */
  collections_bookmark: `<svg xmlns="http://www.w3.org/2000/svg" height="1em" viewBox="0 -960 960 960" width="1em" fill="currentColor"><path d="M560-440 458-498l-98 58v-280h200v280ZM320-280q-33 0-56.5-23.5T240-360v-480q0-33 23.5-56.5T320-920h480q33 0 56.5 23.5T880-840v480q0 33-23.5 56.5T800-280H320Zm0-80h480v-480H320v480ZM160-120q-33 0-56.5-23.5T80-200v-560h80v560h560v80H160Zm160-720v480-480Z"/></svg>`,
  /** Themenseite / Stern / topic */
  topic: `<svg xmlns="http://www.w3.org/2000/svg" height="1em" viewBox="0 -960 960 960" width="1em" fill="currentColor"><path d="m233-240 53-227-176-153 232-20 98-214 98 214 232 20-176 153 53 227-207-125-207 125Zm150-138 124-75 124 75-33-142 110-95-145-13-56-133-56 133-145 13 110 95-33 142Zm124-202Z"/></svg>`,

  // ── Card-Typ-Icons (Inhaltstyp-Ribbon) ─────────────────────────────
  /** Sammlung (Ordner) — universell als "Container von Inhalten" lesbar. */
  auto_stories: `<svg xmlns="http://www.w3.org/2000/svg" height="1em" viewBox="0 -960 960 960" width="1em" fill="currentColor"><path d="M160-160q-33 0-56.5-23.5T80-240v-480q0-33 23.5-56.5T160-800h240l80 80h320q33 0 56.5 23.5T880-640v400q0 33-23.5 56.5T800-160H160Zm0-80h640v-400H447l-80-80H160v480Zm0 0v-480 480Z"/></svg>`,
  /** Video (Play in Frame) */
  play_circle: `<svg xmlns="http://www.w3.org/2000/svg" height="1em" viewBox="0 -960 960 960" width="1em" fill="currentColor"><path d="m380-300 280-180-280-180v360ZM480-80q-83 0-156-31.5T197-197q-54-54-85.5-127T80-480q0-83 31.5-156T197-763q54-54 127-85.5T480-880q83 0 156 31.5T763-763q54 54 85.5 127T880-480q0 83-31.5 156T763-197q-54 54-127 85.5T480-80Zm0-80q134 0 227-93t93-227q0-134-93-227t-227-93q-134 0-227 93t-93 227q0 134 93 227t227 93Zm0-320Z"/></svg>`,
  /** Arbeitsblatt (Dokument mit Linien) */
  article: `<svg xmlns="http://www.w3.org/2000/svg" height="1em" viewBox="0 -960 960 960" width="1em" fill="currentColor"><path d="M320-440h320v-80H320v80Zm0-120h320v-80H320v80Zm0-120h320v-80H320v80ZM240-80q-33 0-56.5-23.5T160-160v-640q0-33 23.5-56.5T240-880h640q33 0 56.5 23.5T720-800v640q0 33-23.5 56.5T640-80H240Zm0-80h400v-640H240v640Zm480 0v-560 560Zm0 0V-720h160v560q0 33-23.5 56.5T720-80Z"/></svg>`,
  /** Interaktiv (Controller) */
  videogame_asset: `<svg xmlns="http://www.w3.org/2000/svg" height="1em" viewBox="0 -960 960 960" width="1em" fill="currentColor"><path d="M160-200q-33 0-56.5-23.5T80-280v-400q0-33 23.5-56.5T160-760h640q33 0 56.5 23.5T880-680v400q0 33-23.5 56.5T800-200H160Zm0-80h640v-400H160v400Zm120-40h80v-120h120v-80H360v-120h-80v120H160v80h120v120Zm280-40q17 0 28.5-11.5T600-400q0-17-11.5-28.5T560-440q-17 0-28.5 11.5T520-400q0 17 11.5 28.5T560-360Zm120-80q17 0 28.5-11.5T720-480q0-17-11.5-28.5T680-520q-17 0-28.5 11.5T640-480q0 17 11.5 28.5T680-440Zm0 160q17 0 28.5-11.5T720-320q0-17-11.5-28.5T680-360q-17 0-28.5 11.5T640-320q0 17 11.5 28.5T680-280Zm120-80q17 0 28.5-11.5T840-400q0-17-11.5-28.5T800-440q-17 0-28.5 11.5T760-400q0 17 11.5 28.5T800-360ZM160-280v-400 400Z"/></svg>`,
  /** Audio (Kopfhörer) */
  headphones: `<svg xmlns="http://www.w3.org/2000/svg" height="1em" viewBox="0 -960 960 960" width="1em" fill="currentColor"><path d="M240-120q-33 0-56.5-23.5T160-200v-280q0-66 25-124t68.5-101.5Q297-749 355-774.5T480-800q67 0 125 25.5t101.5 69Q750-662 775-604t25 124v280q0 33-23.5 56.5T720-120H560v-320h160v-40q0-100-70-170t-170-70q-100 0-170 70t-70 170v40h160v320H240Zm0-80h80v-160h-80v160Zm400 0h80v-160h-80v160ZM240-360h80-80Zm400 0h80-80Z"/></svg>`,
  /** Quiz / Frage */
  quiz: `<svg xmlns="http://www.w3.org/2000/svg" height="1em" viewBox="0 -960 960 960" width="1em" fill="currentColor"><path d="M560-360q17 0 29.5-12.5T602-402q0-17-12.5-29.5T560-444q-17 0-29.5 12.5T518-402q0 17 12.5 29.5T560-360Zm-30-128h60q0-29 6-42.5t28-35.5q30-30 40-48.5t10-43.5q0-45-31.5-73.5T560-760q-41 0-71.5 23T446-676l54 22q9-25 24.5-37.5T560-704q23 0 37.5 12.5T612-658q0 14-8 26t-25 28q-30 27-39.5 47T530-488ZM320-240 160-80v-720q0-33 23.5-56.5T240-880h480q33 0 56.5 23.5T800-800v480q0 33-23.5 56.5T720-240H320Zm-34-80h434v-480H240v525l46-45Zm-46 0v-480 480Z"/></svg>`,
  /** Präsentation (Bild) */
  image: `<svg xmlns="http://www.w3.org/2000/svg" height="1em" viewBox="0 -960 960 960" width="1em" fill="currentColor"><path d="M200-120q-33 0-56.5-23.5T120-200v-560q0-33 23.5-56.5T200-840h560q33 0 56.5 23.5T840-760v560q0 33-23.5 56.5T760-120H200Zm0-80h560v-560H200v560Zm40-80h480L570-480 450-320l-90-120-120 160Zm-40 80v-560 560Z"/></svg>`,
  /** Übung (Bleistift) */
  edit_note: `<svg xmlns="http://www.w3.org/2000/svg" height="1em" viewBox="0 -960 960 960" width="1em" fill="currentColor"><path d="M200-200h57l391-391-57-57-391 391v57Zm0 80q-17 0-28.5-11.5T160-160v-104q0-16 6-30.5t18-25.5l560-560q11-11 25.5-17t30.5-6q16 0 31 6t26 18l55 56q12 11 17.5 26t5.5 30q0 16-5.5 30.5T912-705L353-146q-11 12-25.5 18.5T297-120H200Zm200-320h160v-80H400v80Zm0 160h160v-80H400v80Z"/></svg>`,
  /** Kurs (Diplomhut) */
  school: `<svg xmlns="http://www.w3.org/2000/svg" height="1em" viewBox="0 -960 960 960" width="1em" fill="currentColor"><path d="M479-120 189-279v-240L40-600l439-240 441 240v317h-80v-275l-81 39v240L479-120Zm0-91 220-120v-146L479-360 259-481v146l220 124Zm1-244 273-149-273-146-272 146 272 149Zm-1 124Zm0-122Z"/></svg>`,
  /** Standard Buch (Fallback) */
  menu_book: `<svg xmlns="http://www.w3.org/2000/svg" height="1em" viewBox="0 -960 960 960" width="1em" fill="currentColor"><path d="M560-564v-68q33-14 67.5-21t72.5-7q26 0 51 4t49 10v64q-24-9-48.5-13.5T700-600q-38 0-73 9.5T560-564Zm0 220v-68q33-14 67.5-21t72.5-7q26 0 51 4t49 10v64q-24-9-48.5-13.5T700-380q-38 0-73 9t-67 27Zm0-110v-68q33-14 67.5-21t72.5-7q26 0 51 4t49 10v64q-24-9-48.5-13.5T700-490q-38 0-73 9.5T560-454ZM260-320q47 0 91.5 10.5T440-278v-394q-41-24-87-36t-93-12q-36 0-71.5 7T120-692v396q35-12 69.5-18t70.5-6Zm260 42q44-21 88.5-31.5T700-320q36 0 70.5 6t69.5 18v-396q-33-14-68.5-21t-71.5-7q-47 0-93 12t-87 36v394Zm-40 118q-48-38-104-59t-116-21q-42 0-82.5 11T100-198q-21 11-40.5-1T40-234v-482q0-11 5.5-21T62-752q46-24 96-36t102-12q58 0 113.5 15T480-740q51-30 106.5-45T700-800q52 0 102 12t96 36q11 5 16.5 15t5.5 21v482q0 23-19.5 35t-40.5 1q-37-20-77.5-31T700-240q-60 0-116 21t-104 59ZM280-494Z"/></svg>`,
  /** Standard Buch (Fallback offen) */
  book: `<svg xmlns="http://www.w3.org/2000/svg" height="1em" viewBox="0 -960 960 960" width="1em" fill="currentColor"><path d="M300-80q-58 0-99-41t-41-99v-560q0-58 41-99t99-41h500v600q-25 0-42.5 17.5T740-260q0 25 17.5 42.5T800-200v120H300Zm-60-267q14-7 29-10t31-3h20v-480h-20q-25 0-42.5 17.5T240-780v433Zm160-13h320v-480H400v480Zm-160 13v-493 493Zm60 187h373q-6-14-9.5-28.5T660-220q0-16 3-31t10-29H300q-26 0-43 17.5T240-220q0 26 17 43t43 17Z"/></svg>`,

  // ── Sonstige ───────────────────────────────────────────────────────
  /** Tipp (Glühbirne) */
  lightbulb: `<svg xmlns="http://www.w3.org/2000/svg" height="1em" viewBox="0 -960 960 960" width="1em" fill="currentColor"><path d="M480-80q-33 0-56.5-23.5T400-160h160q0 33-23.5 56.5T480-80ZM320-200v-80h320v80H320Zm10-120q-69-41-109.5-110T180-580q0-125 87.5-212.5T480-880q125 0 212.5 87.5T780-580q0 81-40.5 150T630-320H330Zm24-80h252q45-32 69.5-79T700-580q0-92-64-156t-156-64q-92 0-156 64t-64 156q0 54 24.5 101t69.5 79Zm126 0Z"/></svg>`,
  /** Palette / Canvas leer */
  palette: `<svg xmlns="http://www.w3.org/2000/svg" height="1em" viewBox="0 -960 960 960" width="1em" fill="currentColor"><path d="M480-80q-83 0-156-31.5T197-197q-54-54-85.5-127T80-480q0-83 32.5-156t88-127Q256-817 330-848.5T488-880q80 0 151 27.5t124.5 76q53.5 48.5 85 115T880-518q0 115-70 176.5T640-280h-74q-9 0-12.5 5t-3.5 11q0 12 15 34.5t15 51.5q0 50-27.5 74T480-80Zm0-400Zm-220 40q26 0 43-17t17-43q0-26-17-43t-43-17q-26 0-43 17t-17 43q0 26 17 43t43 17Zm120-160q26 0 43-17t17-43q0-26-17-43t-43-17q-26 0-43 17t-17 43q0 26 17 43t43 17Zm200 0q26 0 43-17t17-43q0-26-17-43t-43-17q-26 0-43 17t-17 43q0 26 17 43t43 17Zm120 160q26 0 43-17t17-43q0-26-17-43t-43-17q-26 0-43 17t-17 43q0 26 17 43t43 17ZM480-160q14 0 23-9t9-23q0-20-15-39.5T482-272q0-46 30-81t76-35h52q69 0 119.5-46T810-561q-4-128-99.5-213.5T488-860q-145 0-246.5 100.5T140-516q5 142 105 240.5T480-160Z"/></svg>`,
  /** Frage / Hilfe */
  help: `<svg xmlns="http://www.w3.org/2000/svg" height="1em" viewBox="0 -960 960 960" width="1em" fill="currentColor"><path d="M484-247q16 0 27-11t11-27q0-16-11-27t-27-11q-16 0-27 11t-11 27q0 16 11 27t27 11Zm-35-146h59q0-26 6.5-47.5T555-490q31-26 44-51t13-55q0-53-34.5-85T486-713q-49 0-86.5 24.5T345-621l53 20q11-28 33-43.5t52-15.5q34 0 55 18.5t21 47.5q0 22-13 41.5T508-512q-30 26-44.5 51.5T449-393Zm31 313q-83 0-156-31.5T197-197q-54-54-85.5-127T80-480q0-83 31.5-156T197-763q54-54 127-85.5T480-880q83 0 156 31.5T763-763q54 54 85.5 127T880-480q0 83-31.5 156T763-197q-54 54-127 85.5T480-80Zm0-80q134 0 227-93t93-227q0-134-93-227t-227-93q-134 0-227 93t-93 227q0 134 93 227t227 93Zm0-320Z"/></svg>`,
} as const;

export type IconName = keyof typeof ICONS;
