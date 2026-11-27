(function () {
  var toggle = document.querySelector('.nav-toggle');
  var nav = document.getElementById('nav');
  if (toggle && nav) {
    toggle.addEventListener('click', function () {
      var open = nav.classList.toggle('open');
      toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    });
  }
  document.querySelectorAll('.js-year').forEach(function (el) {
    el.textContent = String(new Date().getFullYear());
  });

  // GA4 のイベント（site.json の ga_id が空なら gtag がないので何もしない）
  function track(name, params) {
    if (typeof window.gtag === 'function') { window.gtag('event', name, params || {}); }
  }

  // 商品の検索リンク（アフィリエイト）のクリック
  document.addEventListener('click', function (ev) {
    var a = ev.target && ev.target.closest ? ev.target.closest('a[data-shop]') : null;
    if (!a) { return; }
    track('affiliate_click', {
      shop: a.getAttribute('data-shop'),
      item: a.getAttribute('data-item') || '',
      placement: a.getAttribute('data-placement') || '',
      link_url: a.href,
      transport_type: 'beacon'
    });
  });

  // 図解動画：画面に入ったら音なしで一度だけ自動再生（動きを減らす設定・データ節約時は再生しない）
  var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var saveData = navigator.connection && navigator.connection.saveData;
  document.querySelectorAll('video[data-play-in-view]').forEach(function (v) {
    var started = false, auto = false, touched = false;
    v.addEventListener('play', function () {
      if (!started) { started = true; track('video_start', { video_title: v.getAttribute('aria-label') || '' }); }
    });
    v.addEventListener('ended', function () { track('video_complete', { video_title: v.getAttribute('aria-label') || '' }); });
    ['pointerdown', 'keydown'].forEach(function (t) { v.addEventListener(t, function () { touched = true; }); });
    if (reduce || saveData || !('IntersectionObserver' in window)) { return; }
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (en.isIntersecting && en.intersectionRatio >= 0.6) {
          if (!auto && !touched) {
            auto = true;
            v.muted = true;
            var p = v.play();
            if (p && p.catch) { p.catch(function () {}); }
          }
        } else if (auto && !touched && !v.paused) {
          v.pause();
          io.unobserve(v);
        }
      });
    }, { threshold: [0, 0.6] });
    io.observe(v);
  });
})();
