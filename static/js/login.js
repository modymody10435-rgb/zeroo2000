"use strict";

const loginForm = document.getElementById("login-form");

if (loginForm) {
    const usernameInput = document.getElementById("username");
    const passwordInput = document.getElementById("password");
    const usernameField = document.getElementById("username-field");
    const passwordField = document.getElementById("password-field");
    const usernameError = document.getElementById("username-error");
    const passwordError = document.getElementById("password-error");
    const errorBox = document.getElementById("login-error");
    const errorText = document.getElementById("login-error-text");
    const submitButton = document.getElementById("login-submit");
    const revealButton = document.getElementById("toggle-password");
    const loginUrl = loginForm.dataset.loginUrl || "/api/login";

    function setAlert(message) {
        if (!errorBox || !errorText) return;
        errorText.textContent = message || "";
        errorBox.hidden = !message;
    }

    function setFieldError(input, field, errorElement, message) {
        if (!input || !field || !errorElement) return;
        errorElement.textContent = message || "";
        field.classList.toggle("has-error", Boolean(message));
        input.setAttribute("aria-invalid", message ? "true" : "false");
        if (!message) {
            input.removeAttribute("aria-invalid");
        }
    }

    function clearErrors() {
        setAlert("");
        setFieldError(usernameInput, usernameField, usernameError, "");
        setFieldError(passwordInput, passwordField, passwordError, "");
    }

    function validate() {
        clearErrors();
        let valid = true;

        if (!usernameInput.value.trim()) {
            setFieldError(usernameInput, usernameField, usernameError, "يرجى إدخال اسم المستخدم");
            valid = false;
        }

        if (!passwordInput.value) {
            setFieldError(passwordInput, passwordField, passwordError, "يرجى إدخال كلمة المرور");
            valid = false;
        }

        return valid;
    }

    function setLoading(loading) {
        if (!submitButton) return;
        submitButton.disabled = loading;
        submitButton.classList.toggle("is-loading", loading);
        submitButton.setAttribute("aria-busy", loading ? "true" : "false");
    }

    usernameInput.addEventListener("input", () => {
        if (usernameError.textContent) {
            setFieldError(usernameInput, usernameField, usernameError, "");
        }
        setAlert("");
    });

    passwordInput.addEventListener("input", () => {
        if (passwordError.textContent) {
            setFieldError(passwordInput, passwordField, passwordError, "");
        }
        setAlert("");
    });

    if (revealButton) {
        revealButton.addEventListener("click", () => {
            const showing = passwordInput.type === "text";
            passwordInput.type = showing ? "password" : "text";
            revealButton.setAttribute("aria-pressed", showing ? "false" : "true");
            revealButton.setAttribute(
                "aria-label",
                showing ? "إظهار كلمة المرور" : "إخفاء كلمة المرور"
            );
            passwordInput.focus();
        });
    }

    loginForm.addEventListener("submit", async (event) => {
        if (!validate()) {
            event.preventDefault();
            const firstInvalid = loginForm.querySelector(".login-field.has-error input");
            if (firstInvalid) firstInvalid.focus();
            return;
        }

        event.preventDefault();
        setLoading(true);
        setAlert("");

        try {
            const response = await fetch(loginUrl, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    Accept: "application/json",
                },
                credentials: "same-origin",
                body: JSON.stringify({
                    username: usernameInput.value.trim(),
                    password: passwordInput.value,
                    next: loginForm.querySelector('input[name="next"]').value,
                }),
            });

            const data = await response.json().catch(() => ({}));

            if (response.ok && data.ok) {
                window.location.assign(data.redirect || "/forms");
                return;
            }

            setAlert(data.error || "تعذر تسجيل الدخول، حاول مرة أخرى.");
            passwordInput.value = "";
            passwordInput.focus();
        } catch (error) {
            setAlert("تعذر الاتصال بالخادم. تحقق من الاتصال وحاول مرة أخرى.");
        } finally {
            setLoading(false);
        }
    });
}
