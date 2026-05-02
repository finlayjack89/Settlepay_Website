/* =========================================================
   SettlePay — Scroll Reveal (IntersectionObserver)
   Lightweight vanilla JS — no dependencies
   ========================================================= */

(function () {
  'use strict';

  // Respect user motion preferences
  var prefersReducedMotion = window.matchMedia(
    '(prefers-reduced-motion: reduce)'
  ).matches;

  var revealElements = document.querySelectorAll('.reveal');

  if (prefersReducedMotion) {
    // Immediately show everything — no animation
    revealElements.forEach(function (el) {
      el.classList.add('is-visible');
    });
    return;
  }

  var observer = new IntersectionObserver(
    function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          entry.target.classList.add('is-visible');
          observer.unobserve(entry.target); // animate once
        }
      });
    },
    {
      threshold: 0.12,
      rootMargin: '0px 0px -40px 0px',
    }
  );

  revealElements.forEach(function (el) {
    observer.observe(el);
  });
})();
