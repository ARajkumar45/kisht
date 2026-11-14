# Kisht dashboard design system

One stylesheet (`src/styles.css`), shared pieces in `src/ui.tsx`, no CSS framework.
Every colour, space, radius, text size, shadow and timing is a token on `:root`.

## Tokens

| Group | Token | Value | Use |
|---|---|---|---|
| Surface | `--bg` | #f5f6f8 | page background, disabled inputs |
| | `--panel` | #ffffff | cards, tiles, inputs, secondary buttons |
| | `--subtle` | #f8f9fc | row hover, detail rows, skeleton highlight |
| | `--track` | #eef1f6 | bar tracks, neutral badge, agent message |
| | `--line` | #e4e7ec | card and table borders |
| | `--line-strong` | #868fa3 | input and segmented-button borders (3.2:1) |
| Text | `--ink` | #1d2433 | body text (15.5:1 on panel) |
| | `--muted` | #5f677a | secondary text (4.7:1 or more on every surface) |
| | `--on-brand` | #ffffff | text on brand or dark backgrounds |
| Brand | `--brand` / `--brand-soft` | #2f5bea / #e9efff | links, primary button, selected, focus |
| Status | `--good` / `-soft` / `-accent` | #137a4b / #e3f5ec / #2fbf71 | success |
| | `--warn` / `-soft` / `-accent` | #9a6200 / #fff3dc / #e3a008 | caution |
| | `--bad` / `-soft` / `-accent` | #b42318 / #fde9e7 / #e5484d | error, blocked |
| | `--violet` | #8b5cf6 | trace bars for code checks only |
| Sidebar | `--side-bg`, `--side-ink`, `--side-muted` | #141a2a, #c9d0e0, #7d869c | nav, code block |
| | `--side-hover`, `--side-active` | #222a3e, #2a3350 | nav link states, divider |
| Space | `--space-1` to `--space-7` | 2, 4, 6, 8, 12, 16, 24px | all padding, margin, gap |
| Radius | `--radius-xs`, `-sm`, `--radius`, `-lg`, `-pill` | 4, 7, 10, 18, 999px | bars, controls, cards, phone, badges |
| Type | `--text-2xs` to `--text-xl` | 10, 11, 12, 14, 22, 26px | meta, chip, small, body, h1, tile value |
| | `--font`, `--font-mono` | system sans, monospace | text, tool names |
| Shadow | `--shadow` | 0 1px 2px, 6% | cards, tiles, chat bubbles |
| Focus | `--focus`, `--focus-ring` | brand, 3px brand-soft | outline, input halo |
| Motion | `--motion-loop` | 1.4s | live pulse, skeleton shimmer |

Status colours come in three strengths: the plain one for text and borders, `-soft`
for backgrounds behind that text, `-accent` for small non-text marks (dots, bars).
The test chat's four phone colours (`--phone-*`) are set on `.phone` and used nowhere else.

## Components

| Component | Class or function | Variants | States |
|---|---|---|---|
| Button | `button` | primary, `.secondary`, `.danger`, link `a.button` | hover, focus-visible, disabled; busy shows "Saving…" text |
| Segmented | `.seg button` | `.on.pass`, `.on.fail`, `.on.na` | hover, focus-visible, `aria-pressed` |
| Input, select | `input`, `select` | text, checkbox, pill (phone) | focus, disabled; each has an `aria-label` |
| Badge | `Badge`, `OutcomeBadge` | neutral, `good`, `warn`, `bad`, `live` | none (not interactive) |
| Chip | `.chip` | plain, `.tool`, `.bad` | none |
| Card | `Card` | with or without title and right slot | empty: a `.muted` line of text |
| Tile | `Tile` | neutral, `good`, `warn`, `bad` | empty value shows "–" |
| Table | `table` | plain, `.clickable`, `.rules` | row hover, row focus-visible, `tr.dim`, empty row |
| Bars | `Bars`, `.bar-row` | `.bar-fill.low` | empty: "No data yet" |
| Nav | `.side a` | link | hover, focus-visible, `.active` |
| Pick list | `.queue li`, `.people li` | item | hover, focus-visible, `.sel` + `aria-current` |
| Trace row | `.span-row` | by span name, `.bad` | hover, focus-visible, `aria-expanded` |
| Banner | `.banner` | error | `role="alert"`; used for load errors and stale data |
| Inline error | `.error` | error | `role="alert"` |
| Skeleton | `Loading` | loading, error | `role="status"`; shimmer stops under reduced motion |
| Status light | `.dot` | idle, `.ok`, `.warn`, `.down` | always next to a text label |
| Live pulse | `.pulse` | one | labelled "Live"; still under reduced motion |

Clickable rows and list items use `press(fn)` from `ui.tsx`. It adds `tabIndex`,
click, and Enter/Space handling in one place.

## Naming

- Block then part, joined with a dash: `card-head`, `tile-value`, `bar-fill`.
- Tone words are always `good`, `warn`, `bad`, `neutral`, added as a second class.
- State classes in use: `active` (nav, set by the router), `sel` (picked list item),
  `on` (segmented button), `dim` (row that does not apply). Reuse these; do not add more.
- Helpers: `muted`, `small`, `mt`, `wrap`, `clamp`, `chips`, `stack`, `grid-2`, `grid-3`.

## Layout

- Sidebar 210px + content. Under 1200px grids become one column and tiles go 3 across.
- Under 860px the sidebar becomes a scrolling top bar and tiles go 2 across.
- Under 400px form rows wrap so the input sits above its buttons.
- Wide tables scroll sideways inside their card. The page itself never scrolls sideways.
- In the stylesheet, wide breakpoints come first so narrow ones win.

## Accessibility

- Text contrast: body text 4.5:1 or more, on every background it sits on.
- Every link, button, input, row and list item shows a 2px focus outline.
- Landmarks: skip link, `nav` (labelled "Main"), `main`. Page language is `en`.
- Table headers have `scope="col"`.
- Colour is never the only signal: badges carry words, pass/fail marks carry labels.
- Motion: only the live pulse and the skeleton move; both stop under `prefers-reduced-motion`.

## Do

- Use a token for every colour, space, radius and text size. Add a token only if two places need it.
- Use `Badge` with a tone for status. Use `Card` for any boxed section.
- Give every input an `aria-label` or a visible `<label>`.
- Use a real `<button>` for actions. Use `press()` when a whole row must be clickable.
- Show an empty state as one `.muted` sentence saying what will appear there.
- Check any new text-on-background pair for 4.5:1 before using it.

## Don't

- Don't write hex colours, px spacing or px font sizes in rules or in `style={{}}`.
  Inline styles are only for values that come from data (bar width, bar position).
- Don't dim text with `opacity`. Use `--muted`.
- Don't put `--muted` text on a new coloured background without checking contrast.
- Don't use `-accent` colours for text; they are too light on white.
- Don't add `onClick` to a `div`, `tr` or `li` without `press()`.
- Don't add animation without adding it to the reduced-motion rule.
- Don't add a new breakpoint; use the three that exist.

## Known gaps

- The amber `--warn-accent` on tile top borders and low bars is 2.3:1 against white.
  It is decorative there; the number beside it carries the meaning.
- Fixed sizes that are layout, not spacing, stay as plain px: column widths, bar heights,
  avatar and dot sizes, list max-heights.
- On small screens the sidebar status lights are hidden with the footer.
- Transcript text is not tagged with its own language (Hindi, Tamil, Telugu, Kannada).
