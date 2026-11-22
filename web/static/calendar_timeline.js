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
    let labelFrame = null;
    let drag = null;
    let suppressClick = false;

    const updateBarLabels = () => {
        labelFrame = null;
        const labelWidth = content.querySelector('.timeline-corner')?.offsetWidth || 0;
        const viewportLeft = scroll.getBoundingClientRect().left + labelWidth;
        content.querySelectorAll('.timeline-bar').forEach((bar) => {
            const label = bar.querySelector('.timeline-bar-label');
            if (!label) return;
            const barRect = bar.getBoundingClientRect();
            const maxOffset = Math.max(0, bar.clientWidth - label.offsetWidth - 16);
            const desiredOffset = Math.max(0, viewportLeft - barRect.left + 8);
            label.style.transform = `translateX(${Math.min(desiredOffset, maxOffset)}px)`;
        });
    };
    const scheduleBarLabels = () => {
        if (labelFrame === null) labelFrame = requestAnimationFrame(updateBarLabels);
    };

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
        const oldScrollTop = scroll.scrollTop;
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
            scroll.scrollTop = oldScrollTop;
            scheduleBarLabels();
            status.textContent = '';
        } catch (error) {
            status.textContent = 'Не удалось загрузить неделю. Прокрутите ещё раз для повтора.';
        } finally {
            loading = false;
            root.setAttribute('aria-busy', 'false');
        }
    };

    scroll.addEventListener('scroll', () => {
        scheduleBarLabels();
        if (loading) return;
        if (scroll.scrollLeft < 80) {
            loadWeek('previous');
        } else if (scroll.scrollWidth - scroll.clientWidth - scroll.scrollLeft < 80) {
            loadWeek('next');
        }
    });

    scroll.addEventListener('pointerdown', (event) => {
        if (event.pointerType !== 'mouse' || event.button !== 0) return;
        drag = {
            pointerId: event.pointerId, startX: event.clientX, startY: event.clientY,
            scrollLeft: scroll.scrollLeft, active: false,
        };
    });
    scroll.addEventListener('pointermove', (event) => {
        if (!drag || drag.pointerId !== event.pointerId) return;
        const offsetX = event.clientX - drag.startX;
        const offsetY = event.clientY - drag.startY;
        if (!drag.active && Math.abs(offsetX) > 5 && Math.abs(offsetX) > Math.abs(offsetY)) {
            drag.active = true;
            scroll.classList.add('is-dragging');
            scroll.setPointerCapture(event.pointerId);
        }
        if (!drag.active) return;
        event.preventDefault();
        scroll.scrollLeft = drag.scrollLeft - offsetX;
    });
    const finishDrag = (event) => {
        if (!drag || drag.pointerId !== event.pointerId) return;
        if (drag.active) {
            suppressClick = true;
            if (scroll.hasPointerCapture(event.pointerId)) scroll.releasePointerCapture(event.pointerId);
            setTimeout(() => { suppressClick = false; }, 0);
        }
        drag = null;
        scroll.classList.remove('is-dragging');
    };
    scroll.addEventListener('pointerup', finishDrag);
    scroll.addEventListener('pointercancel', finishDrag);
    scroll.addEventListener('dragstart', (event) => {
        if (drag) event.preventDefault();
    });
    scroll.addEventListener('click', (event) => {
        if (!suppressClick) return;
        event.preventDefault();
        event.stopPropagation();
    }, true);
    window.addEventListener('resize', scheduleBarLabels);

    requestAnimationFrame(() => {
        const anchor = content.querySelector(`[data-timeline-date="${root.dataset.anchor}"]`);
        const days = [...content.querySelectorAll('[data-timeline-date]')];
        const anchorIndex = days.indexOf(anchor);
        if (anchor && anchorIndex >= 0) scroll.scrollLeft = anchorIndex * anchor.offsetWidth;
        scheduleBarLabels();
    });
})();
