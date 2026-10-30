# ADR-093: Apple-style frosted glass on the four colours

- **Context:** The operator, 2026-10-30: "ui design is very bad use apple glass morphism ui template". ADR-090's flat white cards on grey were too plain.
- **Options:** (a) adopt a third-party glass template or component kit; (b) keep ADR-090's tokens and structure and change only the look: translucent surfaces, backdrop blur, a soft light behind the page, iOS-style selection; (c) restyle each screen.
- **Choice:** (b). `tokens.css` takes Apple's system colours (blue #007AFF, green, red, orange, with Apple's accessible light variants for text), makes `--surface` translucent and adds `--surface-solid`, `--glass-*` and `--glow-*`. `app/terminal/glass.css` loads after theme.css: glass cards, a sticky glass top bar, a white "thumb" for the selected page and view, pill buttons, heavier glass for dialogs. Dark mode is tokens only, except three hover tints. `prefers-reduced-transparency` turns the glass solid.
- **Why:** No dependency, nothing to license, one file to read or revert. Still four colours, so ADR-090's "a fifth hue is a bug" holds.
- **Cost if wrong:** Backdrop blur costs GPU on long pages; if scrolling stutters on the Mac, drop `--glass-blur` to `none` and the cards stay translucent. On phones the top bar is solid, because a filter there would pin shell.css's fixed bottom nav under it.
