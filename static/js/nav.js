(function () {
    "use strict";

    const sidebar = document.getElementById("sidebar");
    const scrim = document.getElementById("sidebar-scrim");
    const menuButton = document.getElementById("menu-button");

    function toggleSidebar(open) {
        if (!sidebar || !scrim || !menuButton) {
            return;
        }
        sidebar.classList.toggle("open", open);
        scrim.classList.toggle("visible", open);
        document.body.classList.toggle("nav-open", open);
        menuButton.setAttribute("aria-expanded", String(open));
    }

    if (sidebar && scrim && menuButton) {
        menuButton.addEventListener("click", () => toggleSidebar(true));
        scrim.addEventListener("click", () => toggleSidebar(false));
        sidebar.querySelectorAll("a").forEach((link) => {
            link.addEventListener("click", () => toggleSidebar(false));
        });
    }

    window.PolioNav = { toggleSidebar };
})();
