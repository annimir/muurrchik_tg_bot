(() => {
    const root = document.querySelector('[data-calendar-timeline]');
    if (!root) return;

    const scroll = root.querySelector('[data-timeline-scroll]');
    const content = root.querySelector('[data-timeline-content]');
    const status = root.querySelector('[data-timeline-status]');
    const rangeLabel = document.querySelector('[data-timeline-range]');
    const categoryCount = document.querySelector('[data-timeline-category-count]');
    const maxDays = 367;
    let loading = false;

    const shiftDate = (value, days) => {
        const parsed = new Date(`${value}T00:00:00Z`);
        parsed.setUTCDate(parsed.getUTCDate() + days);
        return parsed.toISOString().slice(0, 10);
    };
    const loadedDays = (start, end) => Math.round(
        (new Date(`${end}T00:00:00Z`) - new Date(`${start}T00:00:00Z`)) / 86400000,
    ) + 1;

    const loadWeek = async (direction) => {
        if (loading || loadedDays(root.dataset.start, root.dataset.end) + 7 > maxDays) return;
        const oldStart = root.dataset.start;
        const oldEnd = root.dataset.end;
        const start = direction === 'previous' ? shiftDate(oldStart, -7) : oldStart;
        const end = direction === 'next' ? shiftDate(oldEnd, 7) : oldEnd;
        const oldScrollWidth = scroll.scrollWidth;
        const oldScrollLeft = scroll.scrollLeft;
        const params = new URLSearchParams({
            start, end, game: root.dataset.game, type: root.dataset.type,
        });
        loading = true;
        root.setAttribute('aria-busy', 'true');
        status.textContent = 'Загружаем соседнюю неделю…';
        try {
            const response = await fetch(`/calendar/timeline?${params}`, {
                headers: {'X-Requested-With': 'XMLHttpRequest'}, credentials: 'same-origin',
            });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const data = await response.json();
            content.innerHTML = data.html;
            root.dataset.start = data.start;
            root.dataset.end = data.end;
            rangeLabel.textContent = data.range_label;
            categoryCount.textContent = data.category_count;
            scroll.scrollLeft = direction === 'previous'
                ? oldScrollLeft + scroll.scrollWidth - oldScrollWidth
                : oldScrollLeft;
            status.textContent = '';
        } catch (error) {
            status.textContent = 'Не удалось загрузить неделю. Прокрутите ещё раз для повтора.';
        } finally {
            loading = false;
            root.setAttribute('aria-busy', 'false');
        }
    };

    scroll.addEventListener('scroll', () => {
        if (loading) return;
        if (scroll.scrollLeft < 80) {
            loadWeek('previous');
        } else if (scroll.scrollWidth - scroll.clientWidth - scroll.scrollLeft < 80) {
            loadWeek('next');
        }
    });

    requestAnimationFrame(() => {
        const anchor = content.querySelector(`[data-timeline-date="${root.dataset.anchor}"]`);
        const days = [...content.querySelectorAll('[data-timeline-date]')];
        const anchorIndex = days.indexOf(anchor);
        if (anchor && anchorIndex >= 0) scroll.scrollLeft = anchorIndex * anchor.offsetWidth;
    });
})();
