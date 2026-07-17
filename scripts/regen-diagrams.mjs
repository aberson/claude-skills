#!/usr/bin/env node
/*
 * regen-diagrams.mjs — regenerate the README <picture> diagram SVGs from ONE
 * token source: brand/dist/diagram-palette.json (produced by `onbrand build`,
 * which inherits color.diagram from the shared on-brand house-docs preset that
 * brand/tokens.json extends).
 *
 * ONE geometry -> BOTH themes: each scripts/diagram-templates/<name>.svg.tmpl
 * holds the shared geometry with {{role}} placeholders; this script fills the
 * LIGHT palette to write <name>-light.svg and the DARK palette to write
 * <name>-dark.svg. Re-runnable: edit the preset -> `onbrand build` -> rerun this
 * -> SVGs update. Deterministic (no timestamps in output).
 *
 * The only non-palette color is the drop-shadow flood-color (SHADOW below): a
 * per-theme opacity wash, intentionally NOT a brand-palette role. It is exempt
 * from the palette-trace assert, which covers fill/stroke/stop-color hex only
 * (flood-color is rgba, so a hex scan never sees it).
 *
 * Palette-trace assert (load-bearing "derives from the preset" proof): after
 * writing, every #hex in every regenerated SVG must be a value in that theme's
 * diagram palette. Zero stray literals, or this script exits non-zero.
 *
 * Usage:  node scripts/regen-diagrams.mjs
 */
import { readFileSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(HERE, '..');
const TEMPLATES = path.join(HERE, 'diagram-templates');
const PALETTE = path.join(REPO, 'brand', 'dist', 'diagram-palette.json');

// template base name -> output path base (relative to repo root). The output
// files are <base>-light.svg / <base>-dark.svg — the SAME filenames the README
// <picture> blocks reference.
const OUTPUTS = {
  'core-pipeline': '_shared/core-pipeline',
  'improve-skills': '_shared/improve-skills',
  'routing-web': '_shared/routing-web',
};

// Per-theme drop-shadow flood-color — NOT a palette role (see header).
const SHADOW = { light: 'rgba(20,26,40,.16)', dark: 'rgba(0,0,0,.5)' };

const THEMES = ['light', 'dark'];

function fillTemplate(tmpl, theme, paletteForTheme) {
  const map = { theme, shadow: SHADOW[theme], ...paletteForTheme };
  return tmpl.replace(/\{\{([a-z-]+)\}\}/g, (_m, key) => {
    if (!(key in map)) throw new Error(`unmapped template token {{${key}}} (theme=${theme})`);
    return map[key];
  });
}

/** Every #hex in the SVG must be a value in this theme's diagram palette. */
function assertTraces(svgText, theme, paletteForTheme, label) {
  const allowed = new Set(Object.values(paletteForTheme).map((v) => v.toLowerCase()));
  const hexes = svgText.match(/#[0-9a-fA-F]{3,8}/g) || [];
  const stray = [...new Set(hexes.map((h) => h.toLowerCase()))].filter((h) => !allowed.has(h));
  if (stray.length > 0) {
    throw new Error(`${label}: ${stray.length} stray literal(s) not in ${theme} diagram palette: ${stray.join(', ')}`);
  }
  return hexes.length;
}

function main() {
  const palette = JSON.parse(readFileSync(PALETTE, 'utf8'));
  for (const theme of THEMES) {
    if (!palette[theme]) throw new Error(`diagram-palette.json missing "${theme}" block`);
  }

  let written = 0;
  let tracedHexTotal = 0;
  for (const [name, outBase] of Object.entries(OUTPUTS)) {
    const tmpl = readFileSync(path.join(TEMPLATES, `${name}.svg.tmpl`), 'utf8');
    for (const theme of THEMES) {
      const svg = fillTemplate(tmpl, theme, palette[theme]);
      const outPath = path.join(REPO, `${outBase}-${theme}.svg`);
      const label = path.relative(REPO, outPath).replace(/\\/g, '/');
      // Assert BEFORE writing so a stray literal never lands on disk.
      tracedHexTotal += assertTraces(svg, theme, palette[theme], label);
      writeFileSync(outPath, svg, 'utf8');
      console.log(`  wrote ${label}`);
      written++;
    }
  }
  console.log(
    `regen OK — ${written} SVG(s), every one of ${tracedHexTotal} fill/stroke/stop-color hex traces to brand/dist/diagram-palette.json.`,
  );
}

main();
