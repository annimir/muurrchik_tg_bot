const applyCharacterFilters = (root) => {
    const controls = [...root.querySelectorAll('[data-filter]')];
    const values = Object.fromEntries(controls.map((control) => [
        control.dataset.filter,
        control.value.trim().toLocaleLowerCase(),
    ]));
    const hasActiveFilters = Object.values(values).some(Boolean);
    let visible = 0;

    root.querySelectorAll('[data-character-id]').forEach((card) => {
        const matches = Object.entries(values).every(([key, value]) => {
            if (!value) {
                return true;
            }
            const cardValue = (card.dataset[key] || '').toLocaleLowerCase();
            return key === 'name'
                ? cardValue.includes(value)
                : cardValue.split(' ').includes(value);
        });
        card.hidden = !matches;
        if (matches) {
            visible += 1;
        }
    });

    root.querySelectorAll('[data-tier-row]').forEach((row) => {
        const cards = [...row.querySelectorAll('[data-character-id]')];
        const rowVisible = cards.filter((card) => !card.hidden).length;
        const count = row.querySelector('[data-tier-count]');
        if (count) {
            count.textContent = hasActiveFilters ? `${rowVisible}/${cards.length}` : cards.length;
        }
        row.hidden = hasActiveFilters && rowVisible === 0;
    });

    const countLabel = root.querySelector('[data-filter-count]');
    if (countLabel) {
        countLabel.textContent = hasActiveFilters ? `Показано: ${visible}` : '';
    }
    const empty = root.querySelector('[data-filter-empty]');
    if (empty) {
        empty.hidden = !hasActiveFilters || visible > 0;
    }
};

document.querySelectorAll('[data-tierlist-filters]').forEach((root) => {
    root.querySelectorAll('[data-filter]').forEach((control) => {
        control.addEventListener('input', () => applyCharacterFilters(root));
    });
    root.querySelector('[data-filter-reset]')?.addEventListener('click', () => {
        root.querySelectorAll('[data-filter]').forEach((control) => {
            control.value = '';
        });
        applyCharacterFilters(root);
    });
    applyCharacterFilters(root);
});

const tierlistForm = document.querySelector('#tierlist-editor');

if (tierlistForm) {
    const status = tierlistForm.querySelector('[data-save-status]');
    const saveButton = tierlistForm.querySelector('button[type="submit"]');
    const selectedLabel = tierlistForm.querySelector('[data-selected-character]');
    const zones = [...tierlistForm.querySelectorAll('[data-tier-dropzone]')];
    const cards = [...tierlistForm.querySelectorAll('[data-character-id]')];
    let draggedCard = null;
    let selectedCard = null;
    let dirty = false;
    let dragPointerY = 0;
    let dragScrollFrame = null;

    const stopDragScroll = () => {
        if (dragScrollFrame !== null) {
            cancelAnimationFrame(dragScrollFrame);
            dragScrollFrame = null;
        }
    };

    const animateDragScroll = () => {
        if (!draggedCard) {
            stopDragScroll();
            return;
        }
        const edgeSize = 120;
        let offset = 0;
        if (dragPointerY < edgeSize) {
            offset = -Math.max(4, Math.ceil((edgeSize - dragPointerY) / 8));
        } else if (dragPointerY > window.innerHeight - edgeSize) {
            offset = Math.max(4, Math.ceil((dragPointerY - window.innerHeight + edgeSize) / 8));
        }
        if (offset) {
            window.scrollBy(0, offset);
        }
        dragScrollFrame = requestAnimationFrame(animateDragScroll);
    };

    document.addEventListener('dragover', (event) => {
        if (draggedCard) {
            dragPointerY = event.clientY;
            if (dragScrollFrame === null) {
                dragScrollFrame = requestAnimationFrame(animateDragScroll);
            }
        }
    });

    window.addEventListener('wheel', (event) => {
        if (draggedCard) {
            event.preventDefault();
            window.scrollBy(0, event.deltaY);
        }
    }, {passive: false});

    const setStatus = (text, isError = false) => {
        status.textContent = text;
        status.classList.toggle('is-error', isError);
    };

    const markDirty = () => {
        dirty = true;
        setStatus('Есть несохранённые изменения');
    };

    const updateCounts = () => {
        tierlistForm.querySelectorAll('[data-tier-row]').forEach((row) => {
            const zone = row.querySelector('[data-tier-dropzone]');
            const count = zone.querySelectorAll('[data-character-id]').length;
            row.querySelector('[data-tier-count]').textContent = count;
            row.querySelector('[data-tier-empty]').hidden = count > 0;
        });
    };

    const selectCard = (card) => {
        selectedCard?.classList.remove('is-selected');
        selectedCard = card;
        selectedCard?.classList.add('is-selected');
        selectedLabel.textContent = selectedCard
            ? selectedCard.querySelector('strong').textContent
            : 'никто';
    };

    const moveCard = (card, tier, beforeCard = null) => {
        if (!card) {
            return;
        }
        const zone = tierlistForm.querySelector(`[data-tier-dropzone="${tier}"]`);
        const empty = zone.querySelector('[data-tier-empty]');
        if (beforeCard && beforeCard !== card && beforeCard.parentElement === zone) {
            zone.insertBefore(card, beforeCard);
        } else {
            zone.insertBefore(card, empty);
        }
        card.hidden = false;
        updateCounts();
        applyCharacterFilters(tierlistForm);
        markDirty();
    };

    cards.forEach((card) => {
        card.addEventListener('click', () => selectCard(card));
        card.addEventListener('keydown', (event) => {
            if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault();
                selectCard(card);
            }
        });
        card.addEventListener('dragstart', (event) => {
            draggedCard = card;
            dragPointerY = event.clientY;
            card.classList.add('is-dragging');
            event.dataTransfer.effectAllowed = 'move';
            event.dataTransfer.setData('text/plain', card.dataset.characterId);
        });
        card.addEventListener('dragend', () => {
            card.classList.remove('is-dragging');
            zones.forEach((zone) => zone.classList.remove('is-drag-over'));
            draggedCard = null;
            stopDragScroll();
        });
    });

    zones.forEach((zone) => {
        zone.addEventListener('dragover', (event) => {
            if (!draggedCard) {
                return;
            }
            event.preventDefault();
            event.dataTransfer.dropEffect = 'move';
            zone.classList.add('is-drag-over');
        });
        zone.addEventListener('dragleave', (event) => {
            if (!zone.contains(event.relatedTarget)) {
                zone.classList.remove('is-drag-over');
            }
        });
        zone.addEventListener('drop', (event) => {
            event.preventDefault();
            zone.classList.remove('is-drag-over');
            if (!draggedCard) {
                return;
            }
            const target = event.target.closest('[data-character-id]');
            let beforeCard = target;
            if (target && target !== draggedCard) {
                const bounds = target.getBoundingClientRect();
                beforeCard = event.clientX > bounds.left + bounds.width / 2
                    ? target.nextElementSibling
                    : target;
            }
            moveCard(draggedCard, zone.dataset.tierDropzone, beforeCard);
        });
    });

    tierlistForm.querySelectorAll('[data-move-tier]').forEach((button) => {
        button.addEventListener('click', () => moveCard(selectedCard, button.dataset.moveTier));
    });

    tierlistForm.querySelectorAll('input[name="title"], input[name="games"]').forEach((input) => {
        input.addEventListener('change', markDirty);
    });
    tierlistForm.querySelectorAll('[data-tier-description]').forEach((input) => {
        input.addEventListener('input', markDirty);
    });

    tierlistForm.addEventListener('submit', async (event) => {
        event.preventDefault();
        const entries = zones.flatMap((zone) => (
            [...zone.querySelectorAll('[data-character-id]')].map((card) => ({
                character_id: card.dataset.characterId,
                tier: zone.dataset.tierDropzone,
            }))
        ));
        const descriptions = Object.fromEntries(
            [...tierlistForm.querySelectorAll('[data-tier-description]')].map((input) => [
                input.dataset.tierDescription,
                input.value,
            ]),
        );
        const data = new FormData(tierlistForm);
        data.set('entries', JSON.stringify(entries));
        data.set('tier_descriptions', JSON.stringify(descriptions));
        saveButton.disabled = true;
        setStatus('Сохраняем…');
        try {
            const response = await fetch(tierlistForm.dataset.saveUrl, {
                method: 'POST',
                body: data,
                credentials: 'same-origin',
            });
            const payload = await response.json();
            if (!response.ok) {
                throw new Error(payload.detail || `Ошибка сохранения (${response.status})`);
            }
            tierlistForm.querySelector('input[name="version"]').value = payload.version;
            dirty = false;
            if (payload.notification_sent === false) {
                setStatus('Сохранено, но уведомление в чат не отправлено. Повторим при следующем сохранении.', true);
            } else {
                setStatus('Сохранено');
            }
        } catch (error) {
            setStatus(error.message, true);
        } finally {
            saveButton.disabled = false;
        }
    });

    window.addEventListener('beforeunload', (event) => {
        if (dirty) {
            event.preventDefault();
        }
    });

    updateCounts();
    applyCharacterFilters(tierlistForm);
}
