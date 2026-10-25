(function () {
    const form = document.getElementById("delivery-form");
    if (!form) {
        return;
    }

    const checkboxes = Array.from(
        document.querySelectorAll(".delivery-form-checkbox")
    );
    const selectAll = document.getElementById("select-all-deliveries");
    const selectedCount = document.getElementById("delivery-selected-count");
    const selectedError = document.getElementById("delivery-selected-error");
    const selectedContainer = selectedError
        ? selectedError.closest(".delivery-selected-count")
        : null;
    const recipientName = document.getElementById("recipient-name");
    const deliveryDate = document.getElementById("delivery-date");
    const deliveredBy = document.getElementById("delivered-by");
    const submitButton = form.querySelector('button[type="submit"]');

    function fieldFor(control) {
        return control ? control.closest(".form-field") : null;
    }

    function setFieldError(control, message) {
        const field = fieldFor(control);
        if (!field) {
            return;
        }
        field.classList.add("has-error");
        const error = field.querySelector(".field-error");
        if (error) {
            error.textContent = message;
        }
    }

    function clearFieldError(control) {
        const field = fieldFor(control);
        if (!field) {
            return;
        }
        field.classList.remove("has-error");
        const error = field.querySelector(".field-error");
        if (error) {
            error.textContent = "";
        }
    }

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

    [recipientName, deliveryDate, deliveredBy].forEach((input) => {
        if (!input) {
            return;
        }
        input.addEventListener("input", function () {
            if (input.value.trim()) {
                clearFieldError(input);
            }
        });
    });

    form.addEventListener("submit", function (event) {
        let hasError = false;
        let firstInvalid = null;

        if (!recipientName || !recipientName.value.trim()) {
            setFieldError(recipientName, "اسم المستلم مطلوب");
            hasError = true;
            firstInvalid = firstInvalid || recipientName;
        }

        if (!deliveryDate || !deliveryDate.value.trim()) {
            setFieldError(deliveryDate, "تاريخ التسليم مطلوب");
            hasError = true;
            firstInvalid = firstInvalid || deliveryDate;
        }

        if (!deliveredBy || !deliveredBy.value.trim()) {
            setFieldError(deliveredBy, "اسم الشخص الذي سلّم الاستمارات مطلوب");
            hasError = true;
            firstInvalid = firstInvalid || deliveredBy;
        }

        const selected = checkboxes.some((checkbox) => checkbox.checked);
        if (!selected) {
            setSelectionError("حدد استمارة مراجعة واحدة على الأقل للتسليم");
            hasError = true;
            firstInvalid = firstInvalid || selectedContainer;
        } else {
            setSelectionError("");
        }

        if (hasError) {
            event.preventDefault();
            const target =
                firstInvalid === selectedContainer
                    ? selectedContainer
                    : fieldFor(firstInvalid) || firstInvalid;
            if (target && target.scrollIntoView) {
                target.scrollIntoView({ behavior: "smooth", block: "center" });
            }
            return;
        }

        if (submitButton) {
            submitButton.disabled = true;
        }
    });

    updateSelection(false);
})();
