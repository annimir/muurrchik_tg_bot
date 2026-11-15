const tierlistForm = document.querySelector('#tierlist-editor');

if (tierlistForm) {
    const status = tierlistForm.querySelector('[data-save-status]');
    const saveButton = tierlistForm.querySelector('button[type="submit"]');
    const selectedLabel = tierlistForm.querySelector('[data-selected-character]');
    const filterControls = [...tierlistForm.querySelectorAll('[data-filter]')];
    const zones = [...tierlistForm.querySelectorAll('[data-tier-dropzone]')];
    const cards = [...tierlistForm.querySelectorAll('[data-character-id]')];
    let draggedCard = null;
    let selectedCard = null;
    let dirty = false;

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

    const applyFilters = () => {
        const values = Object.fromEntries(filterControls.map((control) => [
            control.dataset.filter,
            control.value.trim().toLocaleLowerCase(),
        ]));
        let visible = 0;
        tierlistForm.querySelectorAll('[data-tier-dropzone="UNRANKED"] [data-character-id]').forEach((card) => {
            const matches = Object.entries(values).every(([key, value]) => (
                !value || card.dataset[key].toLocaleLowerCase().includes(value)
            ));
            card.hidden = !matches;
            if (matches) {
                visible += 1;
            }
        });
        const countLabel = tierlistForm.querySelector('[data-filter-count]');
        countLabel.textContent = values && Object.values(values).some(Boolean)
            ? `Показано: ${visible}`
            : '';
        tierlistForm.querySelector('[data-filter-empty]').hidden = visible > 0;
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
        applyFilters();
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
            card.classList.add('is-dragging');
            event.dataTransfer.effectAllowed = 'move';
            event.dataTransfer.setData('text/plain', card.dataset.characterId);
        });
        card.addEventListener('dragend', () => {
            card.classList.remove('is-dragging');
            zones.forEach((zone) => zone.classList.remove('is-drag-over'));
            draggedCard = null;
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

    filterControls.forEach((control) => control.addEventListener('input', applyFilters));
    tierlistForm.querySelector('[data-filter-reset]').addEventListener('click', () => {
        filterControls.forEach((control) => {
            control.value = '';
        });
        applyFilters();
    });

    tierlistForm.querySelectorAll('input[name="title"], input[name="games"]').forEach((input) => {
        input.addEventListener('change', markDirty);
    });

    tierlistForm.addEventListener('submit', async (event) => {
        event.preventDefault();
        const entries = zones.flatMap((zone) => (
            [...zone.querySelectorAll('[data-character-id]')].map((card) => ({
                character_id: card.dataset.characterId,
                tier: zone.dataset.tierDropzone,
            }))
        ));
        const data = new FormData(tierlistForm);
        data.set('entries', JSON.stringify(entries));
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
            setStatus('Сохранено');
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
    applyFilters();
}
