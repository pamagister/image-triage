# Image Triage v6 - Detail Selection, Selected Filter, Tooltips and Undo

**Status:** `[ ]` planned
**Created:** 2026-11-17
**Extends:** [`plan_v6_gui_review_and_similar_shots`](plan_v6_gui_review_and_similar_shots.md). The review workspace and visual suggestions already exist; this plan adds the missing selection and feedback layer.
**Target:** make selection available directly in the photo review workspace, add a client-side selected/unselected filter, clarify ambiguous actions with delayed tooltips, and provide a one-step undo for selection-changing bulk actions.

---

## 1. Objective and desired outcome

Version 6 already provides the review workspace, keyboard decisions and visual similarity suggestions. This plan closes the remaining UX gaps:

1. In the photo detail view, the large image and every visual suggestion can be selected or de-selected directly with small checkboxes, using the same browser-local selection as the library.
2. The filter sidebar offers a **Selection** filter with **Any / Selected / Not selected**. It filters the current result page client-side, and a **Review all selected** action opens the existing cross-page review drawer.
3. Key action buttons get explanatory tooltips after about 2.2 seconds. In particular, **Review selection -> Remove** must state that it removes the photo from the selection, not that it changes the accepted/rejected decision. All dialog close buttons use the same subtle red style in the top-right corner.
4. A one-step **Undo** restores the selection before the last selection-changing action, for example **Select all filtered**, **De-select all filtered**, **Clear all**, a best-N run, or removing a photo from the review drawer.

Desired outcome:

> Select photos where they are being reviewed, narrow the current page to selected or unselected photos, understand every ambiguous action, and recover from the last selection mistake.

---

## 2. Scope, constraints and explicit non-goals

### 2.1 In scope

- Detail-page selection controls for the main image and visual suggestions.
- Selected-state styling and a selection count on the detail page.
- Client-side **Selection** filter (Any / Selected / Not selected) in the library sidebar.
- Delayed tooltips for key action buttons.
- Uniform subtle-red close buttons for all HTML dialogs.
- One-step selection undo persisted in `localStorage`.
- Tests, documentation and verification.

### 2.2 Constraints

- Local-first, single-user, no authentication.
- Selection remains browser-local in `localStorage`; no server-side shortlist.
- Accepted/rejected remains content-level in SQLite (`overrides.keep`).
- Keep FastAPI + Jinja + htmx; no SPA rewrite and no Node build step.
- `make fmt`, `make lint`, `make test`, `make syncdocs` and `mkdocs build` must pass.
- Do not edit generated `config.yaml` or `docs/usage/config.md` directly.

### 2.3 Explicit non-goals

- No server-side selected-only filter and no selected-id URL/cookie transport.
- No undo for accepted/rejected status changes.
- No undo for detail-page accept/reject/rating decisions.
- No undo for compare-page selection actions.
- No redo stack; one step is sufficient.
- No tooltip framework or Node dependency; a small shared script is enough.
- No change to stored similarity groups or events.

---

## 3. Architecture and decisions

### 3.1 Detail-page selection

| Area | Decision |
|---|---|
| Selection storage | Existing `image-triage:selected` localStorage array of location ids. |
| Main image | A small checkbox overlay inside `.review-image-frame`, using `data-select-photo` and the current `photo.location_id`. |
| Visual suggestions | Each `similarity.js` card gets a checkbox sibling before the card link, using `data-select-photo` and `item.location_id`. |
| Selected styling | `applySelection()` toggles an `is-selected` class on the closest `.card`, `.similarity-card` or `.review-image-frame`. |
| Dynamic cards | `selection.js` listens for an `image-triage:selection-refresh` event; `similarity.js` dispatches it after rendering suggestions so newly inserted checkboxes reflect the stored selection. |
| Selection count | Add a `data-selected-count` element to the detail heading; the existing selection code updates it. |
| Navigation | The suggestion checkbox is outside the card link, so selecting does not navigate. The card link remains the way to open a suggestion. |

### 3.2 Selected filter

| Area | Decision |
|---|---|
| UI | New **Selection** filter group in the sidebar with radio values `any`, `selected` and `unselected`. |
| Scope | Client-side filter over the currently rendered library page. It composes with server-side filters, folder scope, sorting and pagination. |
| All selected | **Review all selected** opens the existing review drawer, which already loads every selected location across pages via `POST /api/photos`. |
| URL state | `selection` is parsed into `PhotoQuery.selection`, preserved by `base_query` and `_url_with`, and rendered as a removable filter chip. It is not passed to repository filters. |
| API calls | `selection` is stripped from filter maps sent to `/api/photo-ids`, `/api/status` and `/api/select-best`; those endpoints operate on the real server-side filters. |
| Empty state | Show a short note when the active selection filter hides every card on the current page. |
| Documentation | State clearly that this filter applies to the current page and that **Review selection** shows all selected photos. |

### 3.3 Tooltips and dialog close buttons

| Area | Decision |
|---|---|
| Trigger | Hover or keyboard focus for 2200 ms. |
| Implementation | New `static/ui.js` with one fixed-position tooltip element, `role="tooltip"`, `aria-describedby`, viewport clamping and Escape/scroll/blur dismissal. |
| Attribute | `data-tooltip="..."` on key buttons. |
| Scope | Key ambiguous actions only: library bulk actions, review-card actions, dialog close buttons and detail decisions. |
| Remove wording | Review-card button remains **Remove**, with `aria-label="Remove from selection"` and tooltip `Remove this photo from the selection. Accepted/rejected status is unchanged.` |
| Close buttons | One `.dialog-close` style: subtle red text/border on a light background, top-right of the dialog header. |
| Dialogs covered | Export, Review selection and Settings folder browser. |
| Shared behavior | `ui.js` handles `[data-dialog-close]` by closing the closest `<dialog>`. Existing special-case close handlers are removed. |
| Accessibility | Tooltips are supplementary; buttons keep visible text and accessible names. Reduced-motion mode disables animation. |

### 3.4 One-step selection undo

| Area | Decision |
|---|---|
| Storage | New `image-triage:undo` localStorage entry, one object only. |
| Shape | `{ "kind": "selection", "label": "select all filtered", "ids": [ ... ], "created_at": "..." }`. |
| Lifetime | Overwritten by each new undoable selection action; cleared after undo. Survives reloads. |
| Covered actions | Select all filtered, de-select all filtered, clear all, best-N / one-per-group runs, and review-drawer Remove. |
| Not covered | Accepted/rejected changes, detail-page decisions/ratings, compare-page selection, individual tile checkboxes. |
| UI | Hidden **Undo** button in the selection tray. When an undo entry exists, the button is visible with an aria-label and tooltip naming the action. |
| Behavior | Undo writes the previous id array back to localStorage, refreshes all checkboxes and the selection count, applies the active selection filter, then clears the undo entry. No reload is required. |
| Failure handling | If localStorage is unavailable, undo is simply unavailable; selection itself still works for the current page. |

---

## 4. Phases and work packages

Status markers: `[ ]` pending, `[-]` in progress, `[x]` completed.

### Phase 1 - Selection in the photo review workspace `[ ]`

- [ ] P1-W01: Add the main-image selection checkbox and selected-state styling in `photo.html` and `style.css`; show the current selection count in the detail heading.
- [ ] P1-W02: Add a labelled checkbox to every visual suggestion card in `similarity.js`, including an accessible name and a selected-state hook.
- [ ] P1-W03: Add the `image-triage:selection-refresh` event and make `applySelection()` toggle `is-selected` on cards and the detail image frame; dispatch the event after similarity rendering.
- [ ] P1-W04: Add tests for detail markup and browser interaction: select from a suggestion, select the main image, and verify the selection count and localStorage contents.

**Acceptance criteria**

- The main image and each visual suggestion can be selected or de-selected without navigating away.
- Selection changes are reflected immediately in the checkbox state, the detail selection count and the library tray after returning to the library.
- Suggestion checkboxes stay in sync after changing the distance slider or loading more suggestions.
- Keyboard focus and labels are present; selecting a suggestion does not open it.

**Phase gate:** selection works from the review workspace, not only from the library grid.

---

### Phase 2 - Selected / unselected filter `[ ]`

- [ ] P2-W01: Add `PhotoQuery.selection` and parse `any`, `selected`, `unselected` in `query.py`; include it in `base_query`.
- [ ] P2-W02: Preserve `selection` in `_url_with`, add a removable filter chip, pass it to the template, and include it in the filter reset URL.
- [ ] P2-W03: Add the **Selection** filter group to `index.html` with radio controls, a short scope note and a **Review all selected** button.
- [ ] P2-W04: Implement client-side filtering in `selection.js`, bind all `[data-open-review]` controls, add the empty-state note, and strip `selection` from API filter maps.
- [ ] P2-W05: Add tests for query parsing, rendered controls, URL preservation and the client-side filter script.

**Acceptance criteria**

- The sidebar offers Any / Selected / Not selected and preserves the choice through pagination, sorting and folder navigation.
- Selected / Not selected hides matching cards on the current page without changing the stored selection.
- **Review all selected** opens the existing review drawer with all selected locations across pages.
- Server-side actions such as Select all filtered, Accept filtered, Reject filtered and best-N are not narrowed by the client-only selection filter.
- The UI states that the filter applies to the current page.

**Phase gate:** the user can narrow the current page to selected photos and still reach every selected photo across pages.

---

### Phase 3 - Tooltips and uniform dialog close buttons `[ ]`

- [ ] P3-W01: Add `static/ui.js` with the delayed tooltip behavior and generic `[data-dialog-close]` handling; load it from `base.html`.
- [ ] P3-W02: Add `data-tooltip` to key library, review and detail buttons, with special wording for review-card **Remove** and its `aria-label`.
- [ ] P3-W03: Apply the shared `.dialog-close` style and `data-dialog-close` attribute to the export, review and Settings folder-browser dialogs; remove obsolete close handlers from `selection.js` and `settings.js`.
- [ ] P3-W04: Add tests for tooltip attributes, dialog-close markup and the shared script; verify the Settings close button still works.

**Acceptance criteria**

- Hovering or focusing a key button for about 2.2 seconds shows an explanatory tooltip that stays inside the viewport.
- Tooltips disappear on blur, pointer leave, Escape, scroll or click.
- Review-card **Remove** clearly communicates that it changes the selection only.
- All three dialogs have the same subtle red close button in the top-right corner and close with mouse or keyboard.
- Reduced-motion settings do not introduce animation problems.

**Phase gate:** ambiguous actions are self-explanatory and dialogs look consistent.

---

### Phase 4 - One-step selection undo `[ ]`

- [ ] P4-W01: Add undo storage helpers, the hidden **Undo** button and `updateUndoButton()` to `selection.js` and `index.html`.
- [ ] P4-W02: Capture the previous selection before select-all-filtered, de-select-all-filtered, clear-all, best-N / one-per-group, and review-drawer Remove.
- [ ] P4-W03: Implement undo: restore the previous id array, refresh checkboxes, count and selection filter, then clear the undo entry.
- [ ] P4-W04: Add tests for the undo markup, persistence across reload, restoration after each covered action and clearing after undo.

**Acceptance criteria**

- After any covered selection action, **Undo** is visible and names the action.
- One click restores the exact previous selection, including across a page reload.
- Undo is cleared after use and replaced by the next selection action.
- Accepted/rejected decisions are unchanged by undo.
- If localStorage is unavailable, the feature degrades without breaking selection.

**Phase gate:** a mistaken bulk selection can be recovered in one click.

---

### Phase 5 - Verification, documentation and release `[ ]`

- [ ] P5-W01: Run `make fmt`, `make lint`, `make test`, `make syncdocs` and `mkdocs build`; fix regressions.
- [ ] P5-W02: Run the real-browser review workflow and a manual walkthrough covering detail selection, selected filter, tooltips, dialog close buttons and undo.
- [ ] P5-W03: Update `docs/usage/gui.md`, commit, push, confirm CI and report the tracking issue.

**Acceptance criteria**

- All automated checks pass.
- The browser workflow covers the new detail checkboxes, selected filter and undo behavior.
- Documentation matches the implemented behavior and its limitations.
- CI is green on the final commit.

---

## 5. Verification expectations

- **Detail selection:** main image and suggestion checkboxes, no accidental navigation, selection count, persistence into the library tray.
- **Dynamic suggestions:** checkboxes stay correct after slider changes and "Show more".
- **Selection filter:** URL round-trip, page reload, pagination, sort and folder scope; correct empty state; review drawer still shows all selected.
- **API isolation:** client-only `selection` never reaches repository filters or changes bulk status/best-N scopes.
- **Tooltips:** 2.2-second delay, keyboard focus, viewport clamping, dismissal, reduced motion.
- **Dialogs:** all three close buttons share the same style and close correctly.
- **Undo:** every covered action restores the exact prior selection; one step only; survives reload; clears after use; does not touch accepted/rejected.
- **Quality gates:** `make fmt`, `make lint`, `make test`, `make syncdocs`, `mkdocs build`.

---

## 6. Risks and open questions

### 6.1 Risks and mitigations

| Risk | Mitigation |
|---|---|
| The selected filter only covers the current page | State this in the UI and link to **Review all selected**, which is already cross-page. |
| `selection` leaks into server-side filter maps | Strip it in `currentFilters()` / `currentQuery()` and keep it as a separate `PhotoQuery` field. |
| Dynamically rendered suggestion cards miss the stored selection | Dispatch `image-triage:selection-refresh` after rendering and let `selection.js` re-apply. |
| Undo after reload can be stale if the selection changed in another tab | One-step semantics are documented; the undo entry stores the full previous id array, so restoration is deterministic. |
| Tooltips are clipped inside dialogs | Render the tooltip as a fixed-position element on `document.body`. |
| Close-button refactor breaks the Settings folder browser | Cover all three dialogs in tests and the browser workflow. |
| localStorage is unavailable | Undo and selection persistence degrade gracefully; the page remains usable. |

### 6.2 Assumptions

1. The selection filter is intentionally client-side and page-scoped.
2. One-step undo covers selection only; status decisions remain non-undoable in this iteration.
3. Individual tile checkboxes are not undoable; bulk and review-drawer selection actions are.
4. The existing review drawer is the "all selected" view.
5. No configuration or database schema change is required.

### 6.3 Open questions

1. Should the selected filter also be offered as a shortcut in the selection tray, or is the sidebar sufficient?
2. Should undo survive a browser restart, or only reloads within the same session?
3. Should compare-page selection actions receive the same undo treatment in a later iteration?

---

## 7. Progress / Handoff

- **Mode:** autopilot
- **Plan:** `docs/develop/progress/plan_v6_detail_selection_ux.md`
- **Completed:** none
- **Active:** P1-W01 `[-]`
- **Next:** P1-W02
- **Relevant files:** `src/image_triage/gui/templates/photo.html`, `src/image_triage/gui/static/similarity.js`, `src/image_triage/gui/static/selection.js`, `src/image_triage/gui/templates/index.html`, `src/image_triage/gui/query.py`, `src/image_triage/gui/app.py`, `src/image_triage/gui/static/ui.js` (new), `src/image_triage/gui/templates/settings.html`, `src/image_triage/gui/static/settings.js`, `src/image_triage/gui/static/style.css`, `docs/usage/gui.md`
- **Decisions:** selection stays browser-local; selected filter is client-side and page-scoped with the review drawer as the cross-page view; undo is one step and selection-only; tooltips are key-button-only at 2200 ms; all dialogs share one subtle red close style.
- **Blockers:** none
- **Last verified:** 2026-11-17, plan only; no implementation checks run
- **Context status:** clean