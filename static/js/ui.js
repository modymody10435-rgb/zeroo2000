"use strict";

function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, (character) => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#039;",
    })[character]);
}

function formatDateAr(dateString) {
    if (!dateString) return "—";
    const parts = String(dateString).split("-").map(Number);
    if (parts.length !== 3 || parts.some(Number.isNaN)) return dateString;
    const [year, month, day] = parts;
    return `${String(day).padStart(2, "0")}/${String(month).padStart(2, "0")}/${year}`;
}

function formatNumberAr(value) {
    return Number(value || 0).toLocaleString("ar-EG");
}

function showToast(message, type = "success") {
    const region = document.getElementById("toast-region");
    if (!region) return;
    const icon = type === "error" ? "icon-alert" : type === "info" ? "icon-info" : "icon-check";
    const toast = document.createElement("div");
    toast.className = `toast ${type}`;
    toast.innerHTML = `
        <span class="toast-icon">
            <svg class="icon"><use href="#${icon}"></use></svg>
        </span>
        <span>${escapeHtml(message)}</span>
    `;
    region.append(toast);
    window.setTimeout(() => {
        toast.classList.add("hide");
        window.setTimeout(() => toast.remove(), 260);
    }, 3800);
}
