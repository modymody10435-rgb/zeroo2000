(function () {
    "use strict";

    const FORM_URL = "/api/forms";

    const initial = window.FORM_DATA || {};
    const fixedImages = window.FIXED_IMAGES || {};
    const state = {
        id: initial.id || null,
        stampImage: initial.stamp_image || "",
        signatureImage: initial.signature_image || "",
        fixedStamp: fixedImages.stamp || "",
        fixedSignature: fixedImages.signature || "",
    };

    const elements = {
        form: document.getElementById("lab-form"),
        save: document.getElementById("form-save"),
        savePrint: document.getElementById("form-save-print"),
        print: document.getElementById("form-print"),
        remove: document.getElementById("form-delete"),
        alert: document.getElementById("form-alert"),
        alertTitle: document.getElementById("form-alert-title"),
        alertText: document.getElementById("form-alert-text"),
        alertClose: document.getElementById("form-alert-close"),
        idLabel: document.getElementById("form-id-label"),
        savedHint: document.getElementById("saved-hint"),
        notes: document.getElementById("notes"),
        stampFile: document.getElementById("stamp-file"),
        signatureFile: document.getElementById("signature-file"),
        stampFileName: document.getElementById("stamp-file-name"),
        signatureFileName: document.getElementById("signature-file-name"),
        stampClear: document.getElementById("stamp-clear"),
        signatureClear: document.getElementById("signature-clear"),
        showStamp: document.getElementById("show-stamp"),
        showSignature: document.getElementById("show-signature"),
        stampPosition: document.getElementById("stamp-position"),
        signaturePosition: document.getElementById("signature-position"),
        stampMark: document.getElementById("stamp-mark"),
        signatureMark: document.getElementById("signature-mark"),
        stampImage: document.getElementById("stamp-image"),
        signatureImage: document.getElementById("signature-image"),
        stampPlaceholder: document.getElementById("stamp-placeholder"),
        signaturePlaceholder: document.getElementById("signature-placeholder"),
    };

    let busy = false;

    function todayLabel() {
        const now = new Date();
        const iso = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
        return formatDateAr(iso);
    }

    function imageSrc(kind, filename) {
        if (filename) return `${window.UPLOAD_URL}${filename}`;
        return kind === "stamp" ? state.fixedStamp : state.fixedSignature;
    }

    function fileLabel(filename) {
        return filename ? filename : "لم يتم الرفع";
    }

    function applyImage(kind, filename) {
        const image = elements[`${kind}Image`];
        const placeholder = elements[`${kind}Placeholder`];
        const source = imageSrc(kind, filename);
        if (source) {
            image.src = source;
            image.classList.add("is-visible");
            placeholder.hidden = true;
        } else {
            image.removeAttribute("src");
            image.classList.remove("is-visible");
            placeholder.hidden = false;
        }
    }

    function refreshMarks() {
        elements.stampMark.dataset.position = elements.stampPosition.value;
        elements.signatureMark.dataset.position = elements.signaturePosition.value;
        elements.stampMark.hidden = !elements.showStamp.checked;
        elements.signatureMark.hidden = !elements.showSignature.checked;
    }

    function showAlert(title, message, type) {
        elements.alert.hidden = false;
        elements.alert.classList.toggle("is-success", type === "success");
        elements.alertTitle.textContent = title;
        elements.alertText.textContent = message;
    }

    function hideAlert() {
        elements.alert.hidden = true;
    }

    function clearInvalid() {
        elements.form.querySelectorAll('[aria-invalid="true"]').forEach((field) => {
            field.removeAttribute("aria-invalid");
        });
    }

    function showErrors(result) {
        const fields = result.fields || {};
        const messages = Object.values(fields);
        showAlert(
            result.error || "تعذر حفظ الاستمارة",
            messages.length ? messages.join(" · ") : "تحقق من البيانات المدخلة"
        );
        clearInvalid();
        Object.keys(fields).forEach((key) => {
            const field = elements.form.querySelector(`[name="${key}"]`);
            if (field) field.setAttribute("aria-invalid", "true");
        });
        const first = elements.form.querySelector('[aria-invalid="true"]');
        if (first) first.focus();
    }

    function collectPayload() {
        const payload = {};
        new FormData(elements.form).forEach((value, key) => {
            payload[key] = typeof value === "string" ? value.trim() : value;
        });
        payload.notes = elements.notes.value.trim();
        payload.show_stamp = elements.showStamp.checked;
        payload.show_signature = elements.showSignature.checked;
        payload.stamp_image = state.stampImage;
        payload.signature_image = state.signatureImage;
        return payload;
    }

    function applySaved(record) {
        state.id = record.id;
        state.stampImage = record.stamp_image || "";
        state.signatureImage = record.signature_image || "";

        elements.idLabel.textContent = `رقم #${record.id}`;
        elements.remove.hidden = false;
        elements.stampFileName.textContent = fileLabel(state.stampImage);
        elements.signatureFileName.textContent = fileLabel(state.signatureImage);
        elements.stampClear.hidden = !state.stampImage;
        elements.signatureClear.hidden = !state.signatureImage;
        applyImage("stamp", state.stampImage);
        applyImage("signature", state.signatureImage);

        window.history.replaceState({}, "", `/forms/${record.id}`);
        showToast("تم حفظ الاستمارة المعملية");
    }

    async function saveForm() {
        if (busy) return null;
        busy = true;
        elements.save.disabled = true;
        elements.savePrint.disabled = true;
        hideAlert();
        clearInvalid();

        const url = state.id ? `${FORM_URL}/${state.id}` : FORM_URL;
        try {
            const response = await fetch(url, {
                method: state.id ? "PUT" : "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(collectPayload()),
            });
            const result = await response.json().catch(() => ({}));
            if (!response.ok) {
                showErrors(result);
                return null;
            }
            applySaved(result);
            elements.savedHint.hidden = false;
            window.setTimeout(() => {
                elements.savedHint.hidden = true;
            }, 2400);
            return result;
        } catch (error) {
            showAlert("تعذر الاتصال بالخادم", "تحقق من اتصالك ثم أعد المحاولة");
            return null;
        } finally {
            busy = false;
            elements.save.disabled = false;
            elements.savePrint.disabled = false;
        }
    }

    async function deleteForm() {
        if (!state.id) return;
        if (!window.confirm("هل تريد حذف هذه الاستمارة نهائياً؟")) return;
        try {
            const response = await fetch(`${FORM_URL}/${state.id}`, { method: "DELETE" });
            if (response.status === 204) {
                showToast("تم حذف الاستمارة", "info");
                window.setTimeout(() => {
                    window.location.href = "/forms";
                }, 350);
                return;
            }
            const result = await response.json().catch(() => ({}));
            showAlert(result.error || "تعذر حذف الاستمارة", "حاول مرة أخرى");
        } catch (error) {
            showAlert("تعذر الاتصال بالخادم", "تحقق من اتصالك ثم أعد المحاولة");
        }
    }

    function handleImageInput(kind, file) {
        if (!file) return;
        if (!file.type.startsWith("image/")) {
            showAlert("نوع ملف غير مدعوم", "يُسمح برفع صور فقط (PNG أو JPG)");
            elements[`${kind}File`].value = "";
            return;
        }
        if (file.size > 6 * 1024 * 1024) {
            showAlert("الملف كبير جداً", "الحد الأقصى 6 ميجابايت");
            elements[`${kind}File`].value = "";
            return;
        }

        const reader = new FileReader();
        reader.onload = () => {
            state[kind === "stamp" ? "stampImage" : "signatureImage"] = reader.result;
            const image = elements[`${kind}Image`];
            image.src = reader.result;
            image.classList.add("is-visible");
            elements[`${kind}Placeholder`].hidden = true;
            elements[`${kind}FileName`].textContent = file.name;
            elements[`${kind}Clear`].hidden = false;
            hideAlert();
        };
        reader.onerror = () => {
            showAlert("تعذر قراءة الصورة", "أعد اختيار الملف");
        };
        reader.readAsDataURL(file);
    }

    function clearImage(kind) {
        state[kind === "stamp" ? "stampImage" : "signatureImage"] = "";
        elements[`${kind}File`].value = "";
        elements[`${kind}FileName`].textContent = "لم يتم الرفع";
        elements[`${kind}Clear`].hidden = true;
        applyImage(kind, "");
    }

    function datePartsOf(group) {
        return Array.from(group.querySelectorAll(".date-part"));
    }

    function nextDatePart(field) {
        const group = field.closest(".date-field");
        const parts = datePartsOf(group);
        const index = parts.indexOf(field);
        if (index > -1 && parts[index + 1]) return parts[index + 1];
        const groups = Array.from(elements.form.querySelectorAll(".date-field"));
        const groupIndex = groups.indexOf(group);
        for (let i = groupIndex + 1; i < groups.length; i += 1) {
            const first = datePartsOf(groups[i])[0];
            if (first) return first;
        }
        return null;
    }

    function handleDatePartInput(event) {
        const field = event.target;
        if (!field.classList || !field.classList.contains("date-part")) return;
        const max = field.maxLength > 0 ? field.maxLength : 4;
        const cleaned = field.value.replace(/\D/g, "").slice(0, max);
        if (cleaned !== field.value) field.value = cleaned;
        if (cleaned.length < max) return;
        const next = nextDatePart(field);
        if (next) {
            next.focus();
            next.select();
        }
    }

    function handleDatePartKeydown(event) {
        const field = event.target;
        if (!field.classList || !field.classList.contains("date-part")) return;
        if (event.key === "Enter") {
            const next = nextDatePart(field);
            if (next) {
                event.preventDefault();
                next.focus();
                next.select();
            }
            return;
        }
        if (event.key !== "Backspace" || field.value) return;
        const parts = datePartsOf(field.closest(".date-field"));
        const index = parts.indexOf(field);
        if (index > 0 && parts[index - 1]) {
            event.preventDefault();
            parts[index - 1].focus();
            parts[index - 1].select();
        }
    }

    function syncDateGroups() {
        elements.form.querySelectorAll(".date-field").forEach((group) => {
            const day = group.querySelector('[name$="_day"]');
            const month = group.querySelector('[name$="_month"]');
            const year = group.querySelector('[name$="_year"]');
            const hidden = group.querySelector('input[type="hidden"]');
            const dayText = day.value.trim();
            const monthText = month.value.trim();
            const yearText = year.value.trim();
            if (dayText && monthText && yearText) {
                hidden.value = `${yearText.padStart(4, "0")}-${monthText.padStart(2, "0")}-${dayText.padStart(2, "0")}`;
            } else {
                hidden.value = "";
            }
            group.classList.toggle("is-empty", !dayText && !monthText && !yearText);
        });
    }

    function printSheet() {
        hideAlert();
        syncDateGroups();
        window.print();
    }

    function bindEvents() {
        const currentDate = document.getElementById("current-date");
        if (currentDate) currentDate.textContent = todayLabel();

        elements.form.addEventListener("submit", (event) => event.preventDefault());

        elements.save.addEventListener("click", () => saveForm());
        elements.savePrint.addEventListener("click", async () => {
            const saved = await saveForm();
            if (saved) printSheet();
        });
        elements.print.addEventListener("click", printSheet);
        elements.remove.addEventListener("click", deleteForm);
        elements.alertClose.addEventListener("click", hideAlert);

        elements.showStamp.addEventListener("change", refreshMarks);
        elements.showSignature.addEventListener("change", refreshMarks);
        elements.stampPosition.addEventListener("change", refreshMarks);
        elements.signaturePosition.addEventListener("change", refreshMarks);

        elements.stampFile.addEventListener("change", (event) => handleImageInput("stamp", event.target.files[0]));
        elements.signatureFile.addEventListener("change", (event) => handleImageInput("signature", event.target.files[0]));
        elements.stampClear.addEventListener("click", () => clearImage("stamp"));
        elements.signatureClear.addEventListener("click", () => clearImage("signature"));

        elements.form.addEventListener("input", syncDateGroups);
        elements.form.addEventListener("change", syncDateGroups);
        elements.form.addEventListener("input", handleDatePartInput);
        elements.form.addEventListener("keydown", handleDatePartKeydown);
        window.addEventListener("beforeprint", syncDateGroups);

        document.addEventListener("keydown", (event) => {
            if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
                event.preventDefault();
                saveForm();
            }
        });

        if (new URLSearchParams(window.location.search).get("print") === "1") {
            window.addEventListener("load", () => {
                window.setTimeout(printSheet, 450);
            });
        }
    }

    function init() {
        applyImage("stamp", state.stampImage);
        applyImage("signature", state.signatureImage);
        elements.stampFileName.textContent = fileLabel(state.stampImage);
        elements.signatureFileName.textContent = fileLabel(state.signatureImage);
        elements.stampClear.hidden = !state.stampImage;
        elements.signatureClear.hidden = !state.signatureImage;
        elements.idLabel.textContent = state.id ? `رقم #${state.id}` : "لم تُحفظ بعد";
        refreshMarks();
        syncDateGroups();
        bindEvents();
    }

    init();
})();
