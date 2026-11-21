/*-----------------------------------------------------------------------------------

    File: scroll-reveal.js  (GLOBAL)
    Purpose: Adds the .revealed class to any element with .reveal-on-scroll
             once it enters the viewport, which triggers the fade/slide
             transition defined in scroll-reveal.css. Works on any page -
             just add the .reveal-on-scroll class to a section wrapper.

-----------------------------------------------------------------------------------*/

document.addEventListener('DOMContentLoaded', function () {
    var sections = document.querySelectorAll('.reveal-on-scroll');
    if (!sections.length) return;

    if ('IntersectionObserver' in window) {
        var io = new IntersectionObserver(function (entries) {
            entries.forEach(function (entry) {
                if (entry.isIntersecting) {
                    entry.target.classList.add('revealed');
                    io.unobserve(entry.target);
                }
            });
        }, { root: null, rootMargin: '0px 0px -6% 0px', threshold: 0.08 });

        sections.forEach(function (el) { io.observe(el); });
    } else {
        // Fallback for browsers without IntersectionObserver: show everything
        sections.forEach(function (el) { el.classList.add('revealed'); });
    }
});
