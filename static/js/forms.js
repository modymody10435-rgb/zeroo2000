(function () {
    "use strict";

    const state = {
        page: 1,
        perPage: 10,
        pages: 1,
        total: 0,
        search: "",
        governorate: "",
        result: "",
        selected: new Set(),
    };

    const elements = {
        body: document.getElementById("forms-body"),
        empty: document.getElementById("forms-empty"),
        count: document.getElementById("results-count"),
        pageIndicator: document.getElementById("page-indicator"),
        prev: document.getElementById("prev-page"),
        next: document.getElementById("next-page"),
        search: document.getElementById("search-input"),
        governorate: document.getElementById("filter-governorate"),
        result: document.getElementById("filter-result"),
        reset: document.getElementById("reset-filters"),
        summaryTotal: document.getElementById("summary-total"),
        summaryFinalized: document.getElementById("summary-finalized"),
        summaryPending: document.getElementById("summary-pending"),
        summaryPositive: document.getElementById("summary-positive"),
        currentDate: document.getElementById("current-date"),
        selectAll: document.getElementById("select-all-forms"),
        bulkBar: document.getElementById("bulk-bar"),
        selectionCount: document.getElementById("selection-count"),
        exportSelected: document.getElementById("export-selected"),
        clearSelection: document.getElementById("clear-selection"),
    };

    function emptyRow() {
        return `
            <tr class="empty-row">
                <td colspan="11">لا توجد استمارات مطابقة لمعايير البحث الحالية.</td>
            </tr>
        `;
    }

    function updateBulkBar() {
        const count = state.selected.size;
        elements.bulkBar.hidden = count === 0;
        elements.selectionCount.textContent = count
            ? `تم تحديد ${formatNumberAr(count)} استمارة`
            : "لم يتم تحديد أي استمارة";
        elements.exportSelected.disabled = count === 0;

        const boxes = elements.body.querySelectorAll(".row-select");
        const checked = elements.body.querySelectorAll(".row-select:checked").length;
        elements.selectAll.checked = boxes.length > 0 && checked === boxes.length;
        elements.selectAll.indeterminate = checked > 0 && checked < boxes.length;
    }

    function finalResultLabel(item) {
        const value = item.sample2_final || item.sample1_final || "";
        return value || "قيد الإنجاز";
    }

    function badgeClass(value, hasFinal) {
        if (!hasFinal) return "is-progress";
        if (value === "سلبي") return "is-negative";
        if (value === "إيجابي") return "is-positive";
        if (value === "قيد الإنجاز") return "is-progress";
        return "is-muted";
    }

    function rowHtml(item) {
        const age = [];
        if (item.age_months) age.push(`${escapeHtml(item.age_months)} شهر`);
        if (item.age_years) age.push(`${escapeHtml(item.age_years)} سنة`);

        const finalValue = finalResultLabel(item);
        const hasFinal = Boolean(item.sample1_final || item.sample2_final);

        return `
            <tr>
                <td class="select-col">
                    <input class="row-select" type="checkbox" value="${item.id}" ${state.selected.has(item.id) ? "checked" : ""} aria-label="تحديد الاستمارة ${escapeHtml(item.lab_number)}">
                </td>
                <td class="cell-strong">${escapeHtml(item.lab_number) || "—"}</td>
                <td>${escapeHtml(item.patient_name) || "—"}</td>
                <td class="cell-mono">${escapeHtml(item.national_id) || "—"}</td>
                <td>${age.join(" و") || "—"}</td>
                <td>${escapeHtml(item.center) || "—"}</td>
                <td>${escapeHtml(item.governorate) || "—"}</td>
                <td>${escapeHtml(formatDateAr(item.illness_date))}</td>
                <td><span class="lab-badge ${badgeClass(finalValue, hasFinal)}">${escapeHtml(finalValue)}</span></td>
                <td>
                    <span class="creator-chip${item.created_by ? "" : " is-unknown"}" title="منشئ الاستمارة" dir="auto">
                        <svg class="icon"><use href="#icon-user"></use></svg>
                        ${escapeHtml(item.created_by) || "غير معروف"}
                    </span>
                </td>
                <td>
                    <div class="row-actions">
                        <a class="row-action" href="/forms/${item.id}" title="فتح الاستمارة">
                            <svg class="icon"><use href="#icon-edit"></use></svg>
                        </a>
                        <a class="row-action" href="/forms/${item.id}?print=1" title="طباعة الاستمارة">
                            <svg class="icon"><use href="#icon-printer"></use></svg>
                        </a>
                        <button class="row-action delete" type="button" data-delete="${item.id}" title="حذف الاستمارة">
                            <svg class="icon"><use href="#icon-trash"></use></svg>
                        </button>
                    </div>
                </td>
            </tr>
        `;
    }

    function render(payload) {
        const items = payload.items || [];
        state.total = payload.total || 0;
        state.pages = payload.pages || 1;
        state.page = payload.page || 1;

        elements.body.innerHTML = items.length ? items.map(rowHtml).join("") : emptyRow();
        elements.empty.hidden = items.length > 0;

        elements.count.textContent = state.total
            ? `عرض ${items.length} من ${formatNumberAr(state.total)} استمارة`
            : "لا توجد نتائج";
        elements.pageIndicator.textContent = `صفحة ${formatNumberAr(state.page)} من ${formatNumberAr(state.pages)}`;
        elements.prev.disabled = state.page <= 1;
        elements.next.disabled = state.page >= state.pages;

        const summary = payload.summary || {};
        elements.summaryTotal.textContent = formatNumberAr(summary.total || 0);
        elements.summaryFinalized.textContent = formatNumberAr(summary.finalized || 0);
        elements.summaryPending.textContent = formatNumberAr(summary.pending || 0);
        elements.summaryPositive.textContent = formatNumberAr(summary.positive || 0);

        elements.body.querySelectorAll("[data-delete]").forEach((button) => {
            button.addEventListener("click", () => removeForm(Number(button.dataset.delete)));
        });

        elements.body.querySelectorAll(".row-select").forEach((box) => {
            box.addEventListener("change", () => {
                const id = Number(box.value);
                if (box.checked) {
                    state.selected.add(id);
                } else {
                    state.selected.delete(id);
                }
                updateBulkBar();
            });
        });

        updateBulkBar();
    }

    async function removeForm(id) {
        if (!window.confirm("هل تريد حذف هذه الاستمارة نهائياً؟")) return;
        try {
            const response = await fetch(`/api/forms/${id}`, { method: "DELETE" });
            if (response.status === 204) {
                showToast("تم حذف الاستمارة", "info");
                state.selected.delete(id);
                await loadForms();
                return;
            }
            const result = await response.json().catch(() => ({}));
            showToast(result.error || "تعذر حذف الاستمارة", "error");
        } catch (error) {
            showToast("تعذر الاتصال بالخادم", "error");
        }
    }

    async function loadForms() {
        const params = new URLSearchParams({
            page: String(state.page),
            per_page: String(state.perPage),
        });
        if (state.search) params.set("search", state.search);
        if (state.governorate) params.set("governorate", state.governorate);
        if (state.result) params.set("result", state.result);

        try {
            const response = await fetch(`/api/forms?${params.toString()}`);
            if (!response.ok) throw new Error("bad response");
            render(await response.json());
        } catch (error) {
            elements.body.innerHTML = `
                <tr class="empty-row">
                    <td colspan="11">تعذر تحميل الاستمارات، أعد تحميل الصفحة.</td>
                </tr>
            `;
            showToast("تعذر تحميل سجل الاستمارات", "error");
        }
    }

    function bindEvents() {
        if (elements.currentDate) elements.currentDate.textContent = formatDateAr(new Date().toISOString().slice(0, 10));

        let timer;
        elements.search.addEventListener("input", (event) => {
            clearTimeout(timer);
            timer = setTimeout(() => {
                state.search = event.target.value.trim();
                state.page = 1;
                loadForms();
            }, 320);
        });

        elements.governorate.addEventListener("change", (event) => {
            state.governorate = event.target.value;
            state.page = 1;
            loadForms();
        });

        elements.result.addEventListener("change", (event) => {
            state.result = event.target.value;
            state.page = 1;
            loadForms();
        });

        elements.reset.addEventListener("click", () => {
            elements.search.value = "";
            elements.governorate.value = "";
            elements.result.value = "";
            state.search = "";
            state.governorate = "";
            state.result = "";
            state.page = 1;
            loadForms();
        });

        elements.prev.addEventListener("click", () => {
            if (state.page > 1) {
                state.page -= 1;
                loadForms();
            }
        });

        elements.next.addEventListener("click", () => {
            if (state.page < state.pages) {
                state.page += 1;
                loadForms();
            }
        });

        elements.selectAll.addEventListener("change", () => {
            elements.body.querySelectorAll(".row-select").forEach((box) => {
                box.checked = elements.selectAll.checked;
                const id = Number(box.value);
                if (box.checked) {
                    state.selected.add(id);
                } else {
                    state.selected.delete(id);
                }
            });
            updateBulkBar();
        });

        elements.clearSelection.addEventListener("click", () => {
            state.selected.clear();
            elements.body.querySelectorAll(".row-select").forEach((box) => {
                box.checked = false;
            });
            updateBulkBar();
        });

        elements.exportSelected.addEventListener("click", () => {
            if (!state.selected.size) return;
            const ids = Array.from(state.selected).join(",");
            const url = `/forms/batch?ids=${encodeURIComponent(ids)}`;
            const opened = window.open(url, "_blank");
            if (!opened) window.location.href = url;
        });
    }

    bindEvents();
    loadForms();
})();
