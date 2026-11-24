# Homepage enhancement dependencies

These fixed-version files are served by this site (no runtime CDN). They load on
the homepage only, after the static content, and are skipped for reduced-motion
or browsers without WebGL2. The source/dependency files contain their original
notices; the two MIT license texts are included in this directory.

| File | Upstream | License |
| --- | --- | --- |
| `three.module.min.js`, `three.core.js` | [Three.js 0.187.0](https://github.com/mrdoob/three.js/releases/tag/r187); [jsDelivr's minified versions of the pinned npm build files](https://cdn.jsdelivr.net/npm/three@0.187.0/build/) | [MIT](LICENSE-three.txt) |
| `ScrollMagic.min.js` | [ScrollMagic 2.0.9](https://github.com/janpaepke/ScrollMagic/releases/tag/v2.0.9); `scrollmagic/minified/ScrollMagic.min.js` in the npm release | [MIT option](LICENSE-ScrollMagic.md) |
| `gsap.min.js` | [GSAP 3.15.1](https://github.com/greensock/GSAP/releases/tag/3.15.1); `dist/gsap.min.js` in the npm release | [GSAP Standard License](https://gsap.com/standard-license/) |

The first Three.js file is the jsDelivr `three.module.min.js` artifact. Its
unmodified relative import expects the peer to be named `three.core.js`, so we
save jsDelivr's `three.core.min.js` bytes under that filename. ScrollMagic and
GSAP were checked against their npm tarballs. When updating these pinned files,
update the reproducibility checks in `tools/site/tests/test_build.py`.

The current GSAP bundle exposes the official `TweenMax` compatibility name
(`gsap.core.Tween`). ScrollMagic's scene advances this paused tween by
scroll progress; no legacy GSAP 2 bundle, ScrollMagic GSAP plugin or automatic
scroll listener library is needed.
