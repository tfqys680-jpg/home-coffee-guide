// A progressive, decorative enhancement: the labeled static SVG is always present.
const panel = document.querySelector(".ed-extraction");
const figure = panel?.querySelector(".blueprint-figure");
const mount = figure?.querySelector(".blueprint-render");
const motion = window.matchMedia("(prefers-reduced-motion: reduce)");
const vendor = (file) => new URL(`./vendor/${file}`, import.meta.url);
const scriptCache = new Map();

function loadScript(file) {
  if (!scriptCache.has(file)) {
    scriptCache.set(file, new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = vendor(file).href;
      script.async = true;
      script.addEventListener("load", resolve, {once: true});
      script.addEventListener("error", reject, {once: true});
      document.head.append(script);
    }));
  }
  return scriptCache.get(file);
}

function modelGeometry(THREE, rings, segments, volumeLines = segments) {
  const points = [];
  const at = ([y, r], s) => {
    const theta = (2 * Math.PI * s) / segments;
    return [r * Math.cos(theta), y, r * Math.sin(theta)];
  };
  const line = (a, b) => points.push(...a, ...b);
  for (const ring of rings) {
    for (let s = 0; s < segments; s++) line(at(ring, s), at(ring, s + 1));
  }
  for (let s = 0; s < volumeLines; s++) {
    for (let r = 1; r < rings.length; r++) {
      const step = (s * segments) / volumeLines;
      line(at(rings[r - 1], step), at(rings[r], step));
    }
  }
  return new THREE.BufferGeometry().setAttribute("position", new THREE.Float32BufferAttribute(points, 3));
}

function makeWire(THREE, context, canvas) {
  const renderer = new THREE.WebGLRenderer({canvas, context, alpha: true, antialias: true});
  renderer.setClearColor(0x000000, 0);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.65));
  const camera = new THREE.OrthographicCamera(-3, 3, 2.65, -2.65, 0.1, 40);
  camera.position.set(4.5, 3.0, 8.0);
  camera.lookAt(0, 0.15, 0);
  const scene = new THREE.Scene();
  const equipment = new THREE.Group();
  scene.add(equipment);
  const line = new THREE.LineBasicMaterial({color: 0x654935});
  const light = new THREE.LineBasicMaterial({color: 0x654935, transparent: true, opacity: 0.52});
  const geometries = [];
  const mesh = (rings, count, width, material) => {
    const geometry = modelGeometry(THREE, rings, count, width);
    geometries.push(geometry);
    equipment.add(new THREE.LineSegments(geometry, material));
  };
  mesh([[1.45, 1.42], [1.25, 1.31], [.99, 1.13], [.73, .94], [.47, .73], [.21, .49], [.07, .3]], 52, 37, line);
  mesh([[1.45, 1.27], [1.13, 1.03], [.83, .77], [.54, .51], [.23, .24]], 36, 15, light);
  mesh([[-.02, .79], [-.09, .79]], 48, 12, line);
  mesh([[-.59, .84], [-.79, .82], [-1.03, .77], [-1.25, .68], [-1.43, .54]], 42, 28, line);
  const handle = [
    [.78, -.72, 0], [1.08, -.62, 0], [1.31, -.73, 0], [1.36, -.90, 0],
    [1.23, -1.07, 0], [1.01, -1.18, 0], [.73, -1.22, 0]
  ].map((p) => new THREE.Vector3(...p));
  const handleGeo = new THREE.TubeGeometry(new THREE.CatmullRomCurve3(handle), 20, .053, 5, false);
  const edges = new THREE.WireframeGeometry(handleGeo);
  geometries.push(handleGeo, edges);
  equipment.add(new THREE.LineSegments(edges, line));
  const drop = new THREE.LineSegments(modelGeometry(THREE, [[.12, .013], [0, .077], [-.07, .06], [-.11, .015]], 14, 8), light);
  geometries.push(drop.geometry);
  equipment.add(drop);
  function resize() {
    const {width, height} = mount.getBoundingClientRect();
    if (!width || !height) return;
    renderer.setSize(width, height, false);
    const half = 2.65 * width / height;
    camera.left = -half;
    camera.right = half;
    camera.updateProjectionMatrix();
  }
  function render(progress) {
    equipment.rotation.y = -.18 + .33 * progress;
    equipment.rotation.z = -.03 + .085 * progress;
    drop.position.y = -.23 - .18 * progress;
    renderer.render(scene, camera);
  }
  return {
    resize, render,
    dispose() {
      geometries.forEach((item) => item.dispose());
      line.dispose();
      light.dispose();
      renderer.dispose();
    },
  };
}

let stop;
let pending;
let permanentFallback = false;
let inRange = false;

async function start() {
  const canvas = document.createElement("canvas");
  canvas.setAttribute("aria-hidden", "true");
  const context = canvas.getContext("webgl2", {alpha: true, antialias: true});
  if (!context) return;
  // No dependencies are fetched on article pages, without WebGL2, or with reduced motion enabled.
  const [THREE] = await Promise.all([
    import(vendor("three.module.min.js").href),
    loadScript("ScrollMagic.min.js"),
    loadScript("gsap.min.js"),
  ]);
  if (motion.matches || permanentFallback) return;
  const {ScrollMagic, TweenMax} = window;
  if (!ScrollMagic?.Controller || !ScrollMagic?.Scene || !TweenMax?.to) return;

  mount.append(canvas);
  let wire;
  let controller;
  let scrollScene;
  let tween;
  let frame = 0;
  const values = {phase: 0, depth: 0};
  const reset = () => {
    window.removeEventListener("resize", resize);
    window.cancelAnimationFrame(frame);
    tween?.kill();
    scrollScene?.destroy(true);
    controller?.destroy(true);
    wire?.dispose();
    figure.classList.remove("blueprint-enhanced");
    figure.style.removeProperty("--photo-shift");
    canvas.remove();
  };
  const render = () => {
    figure.style.setProperty("--photo-shift", `${values.depth.toFixed(2)}px`);
    wire.render(values.phase);
  };
  const resize = () => {
    window.cancelAnimationFrame(frame);
    frame = window.requestAnimationFrame(() => {
      wire.resize();
      scrollScene.refresh();
      controller.update(true);
      render();
    });
  };
  try {
    wire = makeWire(THREE, context, canvas);
    wire.resize();
    // TweenMax is GSAP 3's official backwards-compatible Tween export. Keep it
    // paused; ScrollMagic is the clock rather than a continuous JS render loop.
    tween = TweenMax.to(values, {duration: 1, phase: 1, depth: 14, paused: true, ease: "none", onUpdate: render});
    controller = new ScrollMagic.Controller({refreshInterval: 0});
    scrollScene = new ScrollMagic.Scene({triggerElement: panel, triggerHook: .82, duration: () => Math.max(1, panel.offsetHeight + window.innerHeight * .22)})
      .on("progress", (event) => tween.progress(event.progress))
      .addTo(controller);
    controller.update(true);
    render();
    figure.classList.add("blueprint-enhanced");
    window.addEventListener("resize", resize, {passive: true});
    canvas.addEventListener("webglcontextlost", () => {
      permanentFallback = true;
      stop?.();
      stop = undefined;
    }, {once: true});
    stop = reset;
  } catch (err) {
    reset();
    throw err;
  }
}

function syncMotion() {
  if (motion.matches) {
    stop?.();
    stop = undefined;
  } else if (inRange && !stop && !pending && !permanentFallback) {
    pending = start().catch(() => { permanentFallback = true; })
      .finally(() => { pending = undefined; });
  }
}
if (mount) {
  motion.addEventListener("change", syncMotion);
  if ("IntersectionObserver" in window) {
    const observer = new IntersectionObserver((entries) => {
      if (!entries.some((entry) => entry.isIntersecting)) return;
      observer.disconnect();
      inRange = true;
      syncMotion();
    }, {rootMargin: "180px 0px"});
    observer.observe(panel);
  } else {
    // Static art remains sufficient on older browsers.
    inRange = false;
  }
}
