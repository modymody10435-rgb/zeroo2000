"use strict";

(function () {
    document.querySelectorAll("form[data-confirm]").forEach((deleteForm) => {
        deleteForm.addEventListener("submit", (event) => {
            if (!window.confirm(deleteForm.dataset.confirm)) {
                event.preventDefault();
            }
        });
    });

    const form = document.getElementById("user-form");
    if (!form) return;

    const username = document.getElementById("username");
    const password = document.getElementById("password");
    const confirm = document.getElementById("password_confirm");
    const usernamePattern = /^[\w.\-]{3,50}$/u;

    function errorElement(input) {
        const field = input.closest(".form-field");
        return field ? field.querySelector(".field-error") : null;
    }

    function setError(input, message) {
        const field = input.closest(".form-field");
        const error = errorElement(input);
        if (field) field.classList.toggle("has-error", Boolean(message));
        if (error) error.textContent = message || "";
        if (message) {
            input.setAttribute("aria-invalid", "true");
        } else {
            input.removeAttribute("aria-invalid");
        }
    }

    function clearError(input) {
        setError(input, "");
    }

    [username, password, confirm].forEach((input) => {
        if (!input) return;
        input.addEventListener("input", () => clearError(input));
    });

    document.querySelectorAll("[data-toggle-password]").forEach((button) => {
        button.addEventListener("click", () => {
            const input = document.getElementById(button.dataset.togglePassword);
            if (!input) return;
            const showing = input.type === "text";
            input.type = showing ? "password" : "text";
            button.setAttribute("aria-pressed", showing ? "false" : "true");
            button.setAttribute(
                "aria-label",
                showing ? "إظهار كلمة المرور" : "إخفاء كلمة المرور"
            );
            input.focus();
        });
    });

    form.addEventListener("submit", (event) => {
        let firstInvalid = null;

        if (username) {
            const usernameValue = username.value.trim();
            if (!usernameValue) {
                setError(username, "يرجى إدخال اسم المستخدم");
                firstInvalid = firstInvalid || username;
            } else if (!usernamePattern.test(usernameValue)) {
                setError(username, "اسم المستخدم 3–50 حرفاً بدون مسافات (حروف وأرقام و . _ -)");
                firstInvalid = firstInvalid || username;
            } else {
                clearError(username);
            }
        }

        if (!password.value) {
            setError(password, "يرجى إدخال كلمة المرور");
            firstInvalid = firstInvalid || password;
        } else if (password.value.length < 8) {
            setError(password, "كلمة المرور يجب ألا تقل عن 8 أحرف");
            firstInvalid = firstInvalid || password;
        } else {
            clearError(password);
        }

        if (!confirm.value) {
            setError(confirm, "يرجى تأكيد كلمة المرور");
            firstInvalid = firstInvalid || confirm;
        } else if (confirm.value !== password.value) {
            setError(confirm, "كلمتا المرور غير متطابقتين");
            firstInvalid = firstInvalid || confirm;
        } else {
            clearError(confirm);
        }

        if (firstInvalid) {
            event.preventDefault();
            firstInvalid.focus();
        }
    });
})();
