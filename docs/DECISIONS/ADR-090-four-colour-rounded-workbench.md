# ADR-090: A four-colour, rounded workbench

- **Context:** The operator asked for a simpler, clearer look with 3-4 solid colours and round corners. The terminal had near-black accents, a different palette per screen (risk book 5 hues plus a blue heatmap, factor chart 9 hues, company chart cyan and purple, market context its own three) and 2-8px corners.
- **Options:** (a) restyle each screen; (b) change the tokens, map every chart palette onto them, and put the look in one last-loaded file; (c) adopt a component library.
- **Choice:** (b). `tokens.css` defines blue (`--brand`: actions, the current page, "this one"), green (`--up`, also `--clear`), red (`--down`, also `--fail`) and amber (`--caveat`) on slate neutrals, with tints `--series-5..7` for charts that need more series. Corners: 10px controls, 14px panels, 18px cards, pills for toggles. `app/terminal/theme.css` loads last and holds the look; `lib/tokens.ts` reads a token for the candle chart, which cannot take `var()`.
- **Why:** One file to read or revert. Any fifth hue is now a bug, findable by `grep '#[0-9a-f]{6}'` outside tokens.css. (c) is a dependency for a restyle.
- **Cost if wrong:** Charts with more than seven series repeat tints; none has more today. Unpushed redesign work on the operator's `ui-revamp` branch may overlap and need merging by hand.
