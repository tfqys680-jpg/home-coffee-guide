// A progressive, decorative enhancement: the labeled static SVG is always present.
const panel = document.querySelector(".ed-extraction");
const figure = panel?.querySelector(".blueprint-figure");
const mount = figure?.querySelector(".blueprint-render");
const button = figure?.querySelector(".blueprint-turn");
const hint = figure?.querySelector(".blueprint-turn-hint");
const staticWire = figure?.querySelector(".blueprint-wire");
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
  const line = new THREE.LineBasicMaterial({color: 0x403b32});
  const light = new THREE.LineBasicMaterial({color: 0x403b32, transparent: true, opacity: 0.52});
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
  function render(turn) {
    equipment.rotation.y = -.18 + turn;
    equipment.rotation.z = -.03;
    drop.position.y = -.23;
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
let spin3D;
let fallbackTurn;

function turnIllustration() {
  if (motion.matches) return;
  if (spin3D) {
    spin3D();
    return;
  }
  if (fallbackTurn || !staticWire?.animate) return;
  // In the static fallback only the artwork rotates, never the focus/hit target.
  const animation = staticWire.animate([{transform: "rotate(0turn)"}, {transform: "rotate(1turn)"}], {
    duration: 1100, easing: "cubic-bezier(.41,.06,.31,.98)"
  });
  fallbackTurn = animation;
  const clear = () => { if (fallbackTurn === animation) fallbackTurn = undefined; };
  animation.finished.then(clear, clear);
}

async function start() {
  const canvas = document.createElement("canvas");
  canvas.setAttribute("aria-hidden", "true");
  const context = canvas.getContext("webgl2", {alpha: true, antialias: true});
  if (!context) { permanentFallback = true; return; }
  // No dependencies are fetched on article pages, without WebGL2, or with reduced motion enabled.
  const [THREE] = await Promise.all([
    import(vendor("three.module.min.js").href),
    loadScript("ScrollMagic.min.js"),
    loadScript("gsap.min.js"),
  ]);
  if (fallbackTurn) await fallbackTurn.finished.catch(() => {});
  if (motion.matches || permanentFallback) return;
  const {ScrollMagic, TweenMax} = window;
  if (!ScrollMagic?.Controller || !ScrollMagic?.Scene || !TweenMax?.to) return;

  mount.append(canvas);
  let wire;
  let controller;
  let scrollScene;
  let tween;
  let turning = false;
  let frame = 0;
  const values = {angle: 0};
  const reset = () => {
    window.removeEventListener("resize", resize);
    window.cancelAnimationFrame(frame);
    spin3D = undefined;
    tween?.kill();
    scrollScene?.destroy(true);
    controller?.destroy(true);
    wire?.dispose();
    figure.classList.remove("blueprint-enhanced");
    canvas.remove();
  };
  const render = () => {
    wire.render(values.angle);
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
    // Keep scrolling static. The existing ScrollMagic scene only refreshes the
    // current pose as the illustration enters view; activation clocks one turn.
    controller = new ScrollMagic.Controller({refreshInterval: 0});
    scrollScene = new ScrollMagic.Scene({triggerElement: panel, triggerHook: .9})
      .on("start", render)
      .addTo(controller);
    spin3D = () => {
      if (turning) return;
      turning = true;
      values.angle = 0;
      tween = TweenMax.to(values, {
        duration: 1.15, angle: Math.PI * 2, ease: "power2.inOut", onUpdate: render,
        onComplete: () => { turning = false; }
      });
    };
    controller.update(true);
    render();
    figure.classList.add("blueprint-enhanced");
    if (button) button.disabled = false;
    if (hint) hint.hidden = false;
    window.addEventListener("resize", resize, {passive: true});
    canvas.addEventListener("webglcontextlost", () => {
      permanentFallback = true;
      stop?.();
      stop = undefined;
      syncMotion();
    }, {once: true});
    stop = reset;
  } catch (err) {
    reset();
    throw err;
  }
}

function syncMotion() {
  if (button) button.disabled = motion.matches || (!staticWire?.animate && !spin3D);
  if (hint) hint.hidden = !button || button.disabled;
  if (motion.matches) {
    fallbackTurn?.cancel();
    fallbackTurn = undefined;
    stop?.();
    stop = undefined;
  } else if (inRange && !stop && !pending && !permanentFallback) {
    pending = start().catch(() => { permanentFallback = true; })
      .finally(() => { pending = undefined; });
  }
}
if (mount && button) {
  button.addEventListener("pointerenter", (event) => {
    if (event.pointerType === "mouse") turnIllustration();
  });
  button.addEventListener("click", turnIllustration);
  syncMotion();
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
