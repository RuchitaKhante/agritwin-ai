/*
 * AgriTwin AI
 * Home page interactions
 *
 * The page is intentionally lightweight.
 * Dashboard API functionality is handled separately
 * by dashboard.js.
 */


/* Smooth scrolling for internal links */

document.querySelectorAll('a[href^="#"]').forEach(link => {

    link.addEventListener('click', function (event) {

        const target =
            document.querySelector(
                this.getAttribute('href')
            );

        if (target) {

            event.preventDefault();

            target.scrollIntoView({
                behavior: 'smooth'
            });

        }

    });

});