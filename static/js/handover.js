(function () {
    const form = document.getElementById("handover-form");
    if (!form) {
        return;
    }

    const checkboxes = Array.from(
        document.querySelectorAll(".delivery-form-checkbox")
    );
    const selectAll = document.getElementById("select-all-handover");
    const selectedCount = document.getElementById("handover-selected-count");
    const selectedError = document.getElementById("handover-selected-error");
    const selectedContainer = selectedError
        ? selectedError.closest(".delivery-selected-count")
        : null;
    const submitButton = form.querySelector('button[type="submit"]');

    function setSelectionError(message) {
        if (selectedError) {
            selectedError.textContent = message;
        }
        if (selectedContainer) {
            selectedContainer.classList.toggle("has-error", Boolean(message));
        }
    }

    function updateSelection(clearError) {
        const selected = checkboxes.filter((checkbox) => checkbox.checked).length;
        if (selectedCount) {
            selectedCount.textContent = String(selected);
        }
        if (selectAll) {
            selectAll.checked = selected > 0 && selected === checkboxes.length;
            selectAll.indeterminate = selected > 0 && selected < checkboxes.length;
        }
        if (clearError && selected > 0) {
            setSelectionError("");
        }
    }

    if (selectAll) {
        selectAll.addEventListener("change", function () {
            checkboxes.forEach((checkbox) => {
                checkbox.checked = selectAll.checked;
            });
            updateSelection(true);
        });
    }

    checkboxes.forEach((checkbox) => {
        checkbox.addEventListener("change", function () {
            updateSelection(true);
        });
    });

    form.addEventListener("submit", function (event) {
        const selected = checkboxes.some((checkbox) => checkbox.checked);
        if (!selected) {
            event.preventDefault();
            setSelectionError("حدد استمارة مراجعة واحدة على الأقل للتسليم");
            if (selectedContainer && selectedContainer.scrollIntoView) {
                selectedContainer.scrollIntoView({ behavior: "smooth", block: "center" });
            }
            return;
        }

        setSelectionError("");
        if (submitButton) {
            submitButton.disabled = true;
        }
    });

    updateSelection(false);
})();
