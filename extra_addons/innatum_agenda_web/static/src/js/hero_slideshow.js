(function () {
    'use strict';

    function initSlideshow() {
        var slides = document.querySelectorAll('.inmed-hero__slide');
        if (slides.length < 2) return;

        var current = 0;
        var interval = 5000;

        setInterval(function () {
            slides[current].classList.remove('inmed-hero__slide--active');
            slides[current].style.transform = 'scale(1)';

            current = (current + 1) % slides.length;

            slides[current].classList.add('inmed-hero__slide--active');
        }, interval);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initSlideshow);
    } else {
        setTimeout(initSlideshow, 100);
    }
    window.addEventListener('load', function () {
        setTimeout(initSlideshow, 200);
    });
})();
