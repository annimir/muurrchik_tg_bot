(() => {
    const form = document.querySelector('[data-cycle-form]');
    if (!form) return;
    const activity = form.querySelector('[data-cycle-activity]');
    const month = form.querySelector('input[name="cycle_month"]');
    const patch = form.querySelector('input[name="patch_start"]');
    const start = form.querySelector('[data-cycle-start]');
    const end = form.querySelector('[data-cycle-end]');
    const iso = (value) => value.toISOString().slice(0, 10);

    const update = (calculateDates = true) => {
        const option = activity.selectedOptions[0];
        const code = option?.dataset.code;
        const rule = option?.dataset.rule;
        form.querySelectorAll('[data-cycle-fields]').forEach((fieldset) => {
            fieldset.hidden = fieldset.dataset.cycleFields !== code;
        });
        form.querySelector('[data-cycle-month-field]').hidden = rule === 'patch_day8';
        form.querySelector('[data-cycle-patch-field]').hidden = rule !== 'patch_day8';
        if (!calculateDates) return;
        if (rule === 'patch_day8') {
            if (!patch.value) return;
            const patchDate = new Date(`${patch.value}T00:00:00Z`);
            const startDate = new Date(patchDate);
            startDate.setUTCDate(startDate.getUTCDate() + 7);
            const endDate = new Date(startDate);
            endDate.setUTCDate(endDate.getUTCDate() + 34);
            start.value = iso(startDate);
            end.value = iso(endDate);
            return;
        }
        if (!month.value) return;
        const [year, monthNumber] = month.value.split('-').map(Number);
        const startDate = new Date(Date.UTC(year, monthNumber - 1, rule === 'month_16' ? 16 : 1));
        const endDate = rule === 'month_16'
            ? new Date(Date.UTC(year, monthNumber, 15))
            : new Date(Date.UTC(year, monthNumber, 0));
        start.value = iso(startDate);
        end.value = iso(endDate);
    };
    activity.addEventListener('change', () => update());
    month.addEventListener('change', () => update());
    patch.addEventListener('change', () => update());
    update(false);
})();
