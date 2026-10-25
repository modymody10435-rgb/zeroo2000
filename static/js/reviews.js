(function () {
    const selectAll = document.getElementById("select-all-forms");
    const checkboxes = Array.from(document.querySelectorAll(".review-form-checkbox"));
    const selectedCount = document.getElementById("selected-count");
    const selectedError = document.getElementById("selected-count-error");
    const selectionLabel = document.getElementById("selection-label");
    const autoNote = document.getElementById("batch-auto-note");
    const selectedCountContainer = selectedCount
        ? selectedCount.closest(".reviews-selected-count")
        : null;
    const applyModeInputs = Array.from(
        document.querySelectorAll('input[name="apply_mode"]')
    );
    const fileInput = document.getElementById("review-pdf");
    const fileLabel = document.getElementById("review-pdf-label");
    const fileError = document.getElementById("review-pdf-error");
    const batchForm = document.querySelector(".reviews-batch-form");
    const batchDetails = document.querySelector(".reviews-batch");
    const reviewerInput = document.getElementById("batch-reviewer");
    const reviewedAtInput = document.getElementById("batch-reviewed-at");

    function errorFieldFor(control) {
        return control
            ? control.closest(".reviews-batch-field, .reviews-file-field")
            : null;
    }

    function setFieldError(control, message) {
        const field = errorFieldFor(control);
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
        const field = errorFieldFor(control);
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
        if (selectedCountContainer) {
            selectedCountContainer.classList.toggle("has-error", Boolean(message));
        }
    }

    function showAutoNote() {
        if (autoNote) {
            autoNote.hidden = false;
        }
    }

    function hideAutoNote() {
        if (autoNote) {
            autoNote.hidden = true;
        }
    }

    function isPdfMode() {
        return applyModeInputs.some(
            (input) => input.value === "pdf" && input.checked
        );
    }

    function applyModeState() {
        const pdfMode = isPdfMode();
        checkboxes.forEach((checkbox) => {
            checkbox.disabled = pdfMode;
        });
        if (selectAll) {
            selectAll.disabled = pdfMode;
        }
        if (selectionLabel) {
            selectionLabel.textContent = pdfMode
                ? "الاستمارات المكتشفة من الملف:"
                : "الاستمارات المحددة:";
        }
        if (pdfMode) {
            if (selectedCount) {
                selectedCount.textContent = "تلقائي";
            }
            setSelectionError("");
            hideAutoNote();
            return;
        }
        updateSelection(false);
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
        if (selected !== checkboxes.length) {
            hideAutoNote();
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
            hideAutoNote();
            updateSelection(true);
        });
    }

    checkboxes.forEach((checkbox) => {
        checkbox.addEventListener("change", function () {
            const selected = checkboxes.filter((item) => item.checked).length;
            if (checkbox.checked && selected === 1 && checkboxes.length > 1) {
                checkboxes.forEach((item) => {
                    item.checked = true;
                });
                showAutoNote();
            }
            updateSelection(true);
        });
    });

    applyModeInputs.forEach((input) => {
        input.addEventListener("change", applyModeState);
    });

    if (fileInput && fileLabel) {
        fileInput.addEventListener("change", function () {
            const file = fileInput.files && fileInput.files[0];
            fileLabel.textContent = file ? file.name : "اختر ملف PDF";
            if (file) {
                clearFieldError(fileInput);
            }
        });
    }

    [reviewerInput, reviewedAtInput].forEach((input) => {
        if (!input) {
            return;
        }
        input.addEventListener("input", function () {
            if (input.value.trim()) {
                clearFieldError(input);
            }
        });
    });

    if (batchForm) {
        batchForm.addEventListener("submit", function (event) {
            let hasError = false;
            let firstInvalid = null;

            const reviewerName = reviewerInput ? reviewerInput.value.trim() : "";
            if (!reviewerName) {
                setFieldError(reviewerInput, "اسم المراجع مطلوب");
                hasError = true;
                firstInvalid = firstInvalid || reviewerInput;
            } else {
                clearFieldError(reviewerInput);
            }

            const reviewedAt = reviewedAtInput ? reviewedAtInput.value.trim() : "";
            if (!reviewedAt) {
                setFieldError(reviewedAtInput, "تاريخ ووقت المراجعة مطلوبان");
                hasError = true;
                firstInvalid = firstInvalid || reviewedAtInput;
            } else {
                clearFieldError(reviewedAtInput);
            }

            if (!isPdfMode()) {
                const selected = checkboxes.some(
                    (checkbox) => checkbox.checked
                );
                if (!selected) {
                    setSelectionError(
                        "اختر استمارة واحدة على الأقل لرفع المراجعة المجمعة"
                    );
                    hasError = true;
                    firstInvalid = firstInvalid || selectedError;
                } else {
                    setSelectionError("");
                }
            } else {
                setSelectionError("");
            }

            const file = fileInput && fileInput.files && fileInput.files[0];
            if (!file) {
                setFieldError(fileInput, "ملف PDF المجمع مطلوب");
                hasError = true;
                firstInvalid = firstInvalid || fileInput || fileError;
            } else {
                clearFieldError(fileInput);
            }

            if (hasError) {
                event.preventDefault();
                if (batchDetails) {
                    batchDetails.open = true;
                }
                const scrollTarget =
                    firstInvalid === selectedError
                        ? selectedCountContainer
                        : errorFieldFor(firstInvalid) || firstInvalid;
                if (scrollTarget && scrollTarget.scrollIntoView) {
                    scrollTarget.scrollIntoView({
                        behavior: "smooth",
                        block: "center",
                    });
                }
            }
        });
    }

    updateSelection(false);
    applyModeState();
})();
