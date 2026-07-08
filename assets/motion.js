(() => {
  const MOTION_KEY = "taobao-dashboard-motion";
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  const toggle = document.getElementById("motionToggle");
  const canvas = document.getElementById("flowCanvas");
  const context = canvas?.getContext("2d");
  const gsapRuntime = window.gsap;
  let frameId = 0;
  let canvasActive = false;
  let observer = null;
  let hasPlayedIntro = false;
  let dashboardData = null;

  function readStoredPreference() {
    try {
      const stored = window.localStorage.getItem(MOTION_KEY);
      if (stored === "on") return true;
      if (stored === "off") return false;
    } catch {
      return !reducedMotion.matches;
    }
    return !reducedMotion.matches;
  }

  let motionEnabled = readStoredPreference();

  function updateToggle() {
    document.body.dataset.motion = motionEnabled ? "on" : "off";
    if (!toggle) return;
    toggle.setAttribute("aria-pressed", String(motionEnabled));
    toggle.querySelector(".motion-toggle-label").textContent = motionEnabled ? "动态" : "静态";
    toggle.setAttribute("aria-label", motionEnabled ? "关闭页面动效" : "开启页面动效");
  }

  function savePreference() {
    try {
      window.localStorage.setItem(MOTION_KEY, motionEnabled ? "on" : "off");
    } catch {
      // Storage may be blocked; the current session still works.
    }
  }

  function resizeCanvas() {
    if (!canvas || !context) return;
    const ratio = Math.min(window.devicePixelRatio || 1, 1.5);
    canvas.width = Math.round(window.innerWidth * ratio);
    canvas.height = Math.round(window.innerHeight * ratio);
    canvas.style.width = `${window.innerWidth}px`;
    canvas.style.height = `${window.innerHeight}px`;
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
  }

  const flowLines = [
    { y: 0.16, amplitude: 38, speed: 0.00018, phase: 0.4, width: 1.2, alpha: 0.22 },
    { y: 0.29, amplitude: 66, speed: 0.00012, phase: 2.1, width: 1.6, alpha: 0.18 },
    { y: 0.47, amplitude: 48, speed: 0.00015, phase: 4.2, width: 1.1, alpha: 0.2 },
    { y: 0.68, amplitude: 74, speed: 0.0001, phase: 1.4, width: 1.4, alpha: 0.14 },
    { y: 0.84, amplitude: 42, speed: 0.0002, phase: 5.1, width: 1, alpha: 0.15 },
  ];

  function drawFlow(timestamp) {
    if (!canvasActive || !canvas || !context) return;
    const width = window.innerWidth;
    const height = window.innerHeight;
    context.clearRect(0, 0, canvas.width, canvas.height);

    const activeLines = width < 640 ? flowLines.filter((_, index) => index % 2 === 0) : flowLines;
    activeLines.forEach((line, index) => {
      const phase = timestamp * line.speed + line.phase;
      const baseY = height * line.y;
      const gradient = context.createLinearGradient(0, 0, width, 0);
      gradient.addColorStop(0, `rgba(32, 217, 210, 0)`);
      gradient.addColorStop(0.22, `rgba(32, 217, 210, ${line.alpha})`);
      gradient.addColorStop(0.64, `rgba(121, 104, 255, ${line.alpha * 0.85})`);
      gradient.addColorStop(1, "rgba(121, 104, 255, 0)");
      context.beginPath();
      context.moveTo(-40, baseY + Math.sin(phase) * line.amplitude);
      context.bezierCurveTo(
        width * 0.24,
        baseY + Math.sin(phase + 1.1 + index * 0.12) * line.amplitude,
        width * 0.68,
        baseY + Math.cos(phase + 0.7) * line.amplitude,
        width + 40,
        baseY + Math.sin(phase + 2.2) * line.amplitude,
      );
      context.strokeStyle = gradient;
      context.lineWidth = line.width;
      context.stroke();

      const packetX = ((timestamp * (0.018 + index * 0.002) + index * 240) % (width + 160)) - 80;
      const packetY = baseY + Math.sin(phase + packetX / Math.max(width, 1) * 4) * line.amplitude;
      const glow = context.createRadialGradient(packetX, packetY, 0, packetX, packetY, 12);
      glow.addColorStop(0, index % 2 ? "rgba(121,104,255,.72)" : "rgba(32,217,210,.8)");
      glow.addColorStop(1, "rgba(32,217,210,0)");
      context.fillStyle = glow;
      context.fillRect(packetX - 12, packetY - 12, 24, 24);
    });

    canvas.dataset.rendered = "true";
    frameId = window.requestAnimationFrame(drawFlow);
  }

  function startCanvas() {
    if (!motionEnabled || document.hidden || canvasActive || !context) return;
    canvasActive = true;
    canvas.dataset.flowState = "running";
    resizeCanvas();
    drawFlow(window.performance.now());
  }

  function stopCanvas() {
    canvasActive = false;
    window.cancelAnimationFrame(frameId);
    if (canvas && context) {
      context.clearRect(0, 0, canvas.width, canvas.height);
      canvas.dataset.flowState = "paused";
      delete canvas.dataset.rendered;
    }
  }

  function animateNumber(element, delay = 0) {
    if (!gsapRuntime || !motionEnabled || !element) return;
    const finalText = element.dataset.finalValue || element.textContent.trim();
    const match = finalText.match(/-?\d+(?:\.\d+)?/);
    if (!match) return;
    const target = Number(match[0]);
    const decimals = match[0].includes(".") ? match[0].split(".")[1].length : 0;
    const counter = { value: 0 };
    gsapRuntime.to(counter, {
      value: target,
      delay,
      duration: 0.72,
      ease: "power3.out",
      onUpdate: () => {
        element.textContent = finalText.replace(match[0], counter.value.toFixed(decimals));
      },
      onComplete: () => {
        element.textContent = finalText;
      },
    });
  }

  function animateScoreBars(scope = document) {
    if (!gsapRuntime || !motionEnabled) return;
    scope.querySelectorAll("[data-score-fill]").forEach((bar, index) => {
      gsapRuntime.fromTo(
        bar,
        { scaleX: 0, transformOrigin: "left center" },
        { scaleX: 1, duration: 0.58, delay: index * 0.035, ease: "expo.out", clearProps: "transform" },
      );
    });
  }

  function playIntro() {
    if (hasPlayedIntro || !gsapRuntime || !motionEnabled) return;
    hasPlayedIntro = true;
    const timeline = gsapRuntime.timeline({ defaults: { overwrite: "auto" } });
    timeline
      .from(".brand-block .eyebrow", { x: -30, opacity: 0, duration: 0.34, ease: "power4.out" }, 0.12)
      .from(".brand-block h1", { y: 42, opacity: 0, duration: 0.72, ease: "expo.out" }, 0.18)
      .from(".command-subtitle", { y: 18, opacity: 0, duration: 0.4, ease: "power2.out" }, 0.38)
      .from(".network-lines path", { strokeDashoffset: 260, opacity: 0, duration: 0.8, stagger: 0.07, ease: "sine.out" }, 0.18)
      .from(".network-node", { scale: 0.62, opacity: 0, duration: 0.46, stagger: 0.08, ease: "back.out(1.25)" }, 0.3)
      .from(".command-meta > *", { x: 28, opacity: 0, duration: 0.42, stagger: 0.08, ease: "power3.out" }, 0.42)
      .from(".metric", { y: 34, opacity: 0, duration: 0.48, stagger: 0.055, ease: "power3.out" }, 0.5)
      .from(".today-brief", { y: 38, opacity: 0, scale: 0.985, duration: 0.62, ease: "expo.out" }, 0.7)
      .from(".freshness-ring", { rotation: -110, scale: 0.72, opacity: 0, duration: 0.68, ease: "back.out(1.4)" }, 0.84)
      .from(".top-card", { y: 42, opacity: 0, scale: 0.975, duration: 0.62, stagger: 0.1, ease: "power4.out" }, 0.88);

    document.querySelectorAll(".metric-value").forEach((element, index) => animateNumber(element, 0.58 + index * 0.055));
    animateNumber(document.querySelector(".freshness-ring strong"), 0.86);
    animateScoreBars(document);
  }

  function animateCards(cards, variant = "standard") {
    if (!gsapRuntime || !motionEnabled || !cards.length) return;
    const distance = variant === "risk" ? 26 : variant === "signal" ? 34 : 30;
    gsapRuntime.fromTo(
      cards,
      { y: distance, opacity: 0, scale: variant === "risk" ? 0.985 : 0.975 },
      {
        y: 0,
        opacity: 1,
        scale: 1,
        duration: variant === "signal" ? 0.46 : 0.58,
        stagger: Math.min(0.07, 0.42 / cards.length),
        ease: variant === "risk" ? "power2.out" : "expo.out",
        clearProps: "transform,opacity",
      },
    );
    cards.forEach((card) => animateScoreBars(card));
    if (variant === "risk") {
      gsapRuntime.fromTo(
        cards,
        { boxShadow: "0 0 0 rgba(255,91,104,0)" },
        { boxShadow: "0 0 28px rgba(255,91,104,.16)", duration: 0.34, yoyo: true, repeat: 1, ease: "sine.inOut" },
      );
    }
  }

  function observeSections() {
    observer?.disconnect();
    if (!motionEnabled || !("IntersectionObserver" in window)) return;
    observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting || entry.target.dataset.motionSeen === "true") return;
          entry.target.dataset.motionSeen = "true";
          const cards = [...entry.target.querySelectorAll(".product-card, .signal-card, .avoid-card, .step-card, .rule-item")];
          const variant = entry.target.id === "avoidGrid" ? "risk" : entry.target.classList.contains("signal-rail") ? "signal" : "standard";
          animateCards(cards.length ? cards : [entry.target], variant);
          observer.unobserve(entry.target);
        });
      },
      { threshold: 0.12, rootMargin: "0px 0px -8% 0px" },
    );

    document
      .querySelectorAll("#operatorGuide, #productGrid, #trackingGrid, #radarGrid, #avoidGrid, .rules")
      .forEach((section) => observer.observe(section));
  }

  function resetAnimatedStyles() {
    if (!gsapRuntime) return;
    const targets = document.querySelectorAll(
      ".brand-block *, .network-node, .network-lines path, .command-meta > *, .metric, .today-brief, .freshness-ring, .top-card, .product-card, .signal-card, .avoid-card, .step-card, .rule-item, [data-score-fill]",
    );
    gsapRuntime.killTweensOf(targets);
    gsapRuntime.set(targets, { clearProps: "all" });
    document.querySelectorAll("[data-final-value]").forEach((element) => {
      element.textContent = element.dataset.finalValue;
    });
  }

  function setMotion(nextValue, persist = true) {
    motionEnabled = nextValue;
    updateToggle();
    if (canvas) canvas.style.opacity = motionEnabled ? "" : "0";
    if (persist) savePreference();
    if (motionEnabled) {
      document.querySelectorAll("[data-motion-seen]").forEach((element) => delete element.dataset.motionSeen);
      startCanvas();
      observeSections();
    } else {
      stopCanvas();
      observer?.disconnect();
      resetAnimatedStyles();
    }
  }

  function animateFilterResults() {
    if (!motionEnabled) return;
    const grid = document.getElementById("productGrid");
    if (!grid) return;
    animateCards([...grid.querySelectorAll(".product-card")], "standard");
  }

  function animateRail({ mode, direction }) {
    if (!gsapRuntime || !motionEnabled) return;
    const rail = document.getElementById(`${mode}Grid`);
    if (!rail) return;
    window.requestAnimationFrame(() => {
      gsapRuntime.fromTo(
        [...rail.querySelectorAll(".signal-card")],
        { x: direction * 24, opacity: 0.58 },
        { x: 0, opacity: 1, duration: 0.42, stagger: 0.035, ease: "power3.out", clearProps: "transform,opacity" },
      );
    });
  }

  toggle?.addEventListener("click", () => setMotion(!motionEnabled));
  window.addEventListener("resize", resizeCanvas, { passive: true });
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) stopCanvas();
    else startCanvas();
  });
  reducedMotion.addEventListener("change", (event) => {
    try {
      if (window.localStorage.getItem(MOTION_KEY) === null) setMotion(!event.matches, false);
    } catch {
      setMotion(!event.matches, false);
    }
  });

  window.addEventListener("dashboard:ready", (event) => {
    dashboardData = event.detail?.data || null;
    if (dashboardData) document.body.dataset.catalogSize = String(dashboardData.catalogSize || 0);
    playIntro();
    observeSections();
  });
  window.addEventListener("dashboard:products-updated", (event) => {
    if (event.detail?.reason === "filter") animateFilterResults();
  });
  window.addEventListener("dashboard:rail-move", (event) => animateRail(event.detail || {}));

  updateToggle();
  startCanvas();
  if (document.body.dataset.dashboardReady === "true") {
    playIntro();
    observeSections();
  }
})();
