/* Navigation only. All financial values are computed by Python. */
(() => {
  const links = Array.from(document.querySelectorAll('.fb-nav a'));
  const current = () => {
    links.forEach(link => {
      if (link.hash === (location.hash || '#quality')) link.setAttribute('aria-current', 'location');
      else link.removeAttribute('aria-current');
    });
  };
  addEventListener('hashchange', current);
  current();
  const print = document.querySelector('[data-print]');
  if (print) { print.hidden = false; print.addEventListener('click', () => window.print()); }
})();
