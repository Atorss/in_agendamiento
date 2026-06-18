(function () {
    'use strict';

    function initScrollAnimations() {
        var wrap = document.querySelector('.odonto-home');
        if (!wrap) return;

        var selectors = [
            '.odonto-card',
            '.odonto-facial-card',
            '.odonto-doctor-card',
            '.odonto-section__header',
            '.odonto-quote__inner',
            '.odonto-infocard',
            '.odonto-video',
            '.odonto-contact-form',
            '.odonto-about__image',
            '.odonto-hero__image',
        ];

        var elements = wrap.querySelectorAll(selectors.join(','));
        if (!elements.length) return;

        // Add hidden state + stagger delay for siblings
        elements.forEach(function (el) {
            el.style.opacity = '0';
            el.style.transform = 'translateY(40px)';
            el.style.transition = 'opacity 0.6s ease, transform 0.6s ease';

            // Stagger cards
            var col = el.closest('[class*="col-"]');
            if (col && col.parentElement) {
                var cols = col.parentElement.children;
                for (var i = 0; i < cols.length; i++) {
                    if (cols[i] === col) {
                        el.style.transitionDelay = (i * 0.12) + 's';
                        break;
                    }
                }
            }
        });

        // Hero special - slide from sides
        var heroTitle = wrap.querySelector('.odonto-hero__title');
        var heroAccent = wrap.querySelector('.odonto-hero__accent');
        var heroImg = wrap.querySelector('.odonto-hero__image');
        var heroCta = wrap.querySelector('.odonto-hero .odonto-btn');

        if (heroTitle) {
            heroTitle.style.opacity = '0';
            heroTitle.style.transform = 'translateX(-50px)';
            heroTitle.style.transition = 'opacity 0.8s ease, transform 0.8s ease';
        }
        if (heroAccent) {
            heroAccent.style.opacity = '0';
            heroAccent.style.transform = 'translateX(-50px)';
            heroAccent.style.transition = 'opacity 0.8s ease 0.2s, transform 0.8s ease 0.2s';
        }
        if (heroCta) {
            heroCta.style.opacity = '0';
            heroCta.style.transform = 'translateY(20px)';
            heroCta.style.transition = 'opacity 0.8s ease 0.4s, transform 0.8s ease 0.4s';
        }
        if (heroImg) {
            heroImg.style.opacity = '0';
            heroImg.style.transform = 'translateX(50px) scale(0.95)';
            heroImg.style.transition = 'opacity 1s ease 0.3s, transform 1s ease 0.3s';
        }

        // Show hero immediately (above fold)
        setTimeout(function () {
            if (heroTitle) { heroTitle.style.opacity = '1'; heroTitle.style.transform = 'translateX(0)'; }
            if (heroAccent) { heroAccent.style.opacity = '1'; heroAccent.style.transform = 'translateX(0)'; }
            if (heroCta) { heroCta.style.opacity = '1'; heroCta.style.transform = 'translateY(0)'; }
            if (heroImg) { heroImg.style.opacity = '1'; heroImg.style.transform = 'translateX(0) scale(1)'; }
        }, 100);

        // IntersectionObserver for scroll elements
        if ('IntersectionObserver' in window) {
            var observer = new IntersectionObserver(function (entries) {
                entries.forEach(function (entry) {
                    if (entry.isIntersecting) {
                        entry.target.style.opacity = '1';
                        entry.target.style.transform = 'translateY(0)';
                        observer.unobserve(entry.target);
                    }
                });
            }, {
                threshold: 0.1,
                rootMargin: '0px 0px -40px 0px'
            });

            elements.forEach(function (el) {
                observer.observe(el);
            });
        } else {
            // Fallback
            elements.forEach(function (el) {
                el.style.opacity = '1';
                el.style.transform = 'translateY(0)';
            });
        }
    }

    // Run when ready - try multiple hooks for Odoo compatibility
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initScrollAnimations);
    } else {
        // DOM already loaded, run after a tick for Odoo rendering
        setTimeout(initScrollAnimations, 200);
    }

    // Also listen for Odoo SPA navigation
    window.addEventListener('load', function () {
        setTimeout(initScrollAnimations, 300);
    });

    // ===== HERO SLIDESHOW =====
    function initSlideshow() {
        var slides = document.querySelectorAll('.odonto-hero__slide');
        if (slides.length < 2) return;

        var current = 0;
        var interval = 5000; // 5 seconds per slide

        setInterval(function () {
            // Remove active from current
            slides[current].classList.remove('odonto-hero__slide--active');
            // Reset scale for outgoing
            slides[current].style.transform = 'scale(1)';

            // Next slide
            current = (current + 1) % slides.length;

            // Activate next
            slides[current].classList.add('odonto-hero__slide--active');
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
