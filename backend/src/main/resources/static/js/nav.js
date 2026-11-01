/* =====================================================
   CONTACT US NAVIGATION
===================================================== */

const contactBtn = document.getElementById("contact-btn");
const contactPanel = document.getElementById("contact-panel");


/* =====================================================
   OPEN / CLOSE CONTACT PANEL
===================================================== */

if (contactBtn && contactPanel) {

    contactBtn.addEventListener("click", function (event) {

        event.stopPropagation();

        contactPanel.classList.toggle("show");

    });


    /* =================================================
       CLOSE WHEN CLICKING OUTSIDE
    ================================================= */

    document.addEventListener("click", function (event) {

        if (
            !contactPanel.contains(event.target) &&
            !contactBtn.contains(event.target)
        ) {
            contactPanel.classList.remove("show");
        }

    });


    /* =================================================
       CLOSE WITH ESCAPE KEY
    ================================================= */

    document.addEventListener("keydown", function (event) {

        if (event.key === "Escape") {
            contactPanel.classList.remove("show");
        }

    });

}