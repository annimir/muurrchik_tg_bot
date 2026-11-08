const wishPullButton = document.querySelector('#wish-pull');
if (wishPullButton) {
    const animation = document.querySelector('#wish-animation');
    const results = document.querySelector('#wish-results');
    const skipButton = document.querySelector('#wish-skip');
    const csrfToken = document.querySelector('input[name="csrf_token"]').value;
    let animationTimer;

    const showWishError = (message) => {
        if (typeof showAdminToast === 'function') {
            showAdminToast(message, true);
        } else {
            window.alert(message);
        }
    };

    const updateParticipant = (participant) => {
        document.querySelector('#wish-remaining').textContent = participant.remaining;
        document.querySelector('#wish-pity5').textContent = participant.pity5;
        document.querySelector('#wish-pity4').textContent = participant.pity4;
        document.querySelector('#wish-guarantee').textContent = participant.featured5_guaranteed
            ? 'Следующий 5★ гарантированно featured'
            : '50/50 на следующий 5★';
        wishPullButton.disabled = participant.remaining < 10;
    };

    const updateStats = (stats) => {
        const body = document.querySelector('#wish-stats-body');
        body.replaceChildren();
        if (!stats.length) {
            const row = document.createElement('tr');
            const cell = document.createElement('td');
            cell.colSpan = 10;
            cell.textContent = 'Пока никто не сделал молитв.';
            row.appendChild(cell);
            body.appendChild(row);
            return;
        }
        stats.forEach((stat) => {
            const row = document.createElement('tr');
            const average = stat.average_five_pity === null ? '—' : Number(stat.average_five_pity).toFixed(1);
            const values = [
                stat.tag || stat.id, stat.used, stat.remaining, stat.five_star_count,
                stat.featured_five_count, stat.four_star_count, stat.three_star_count,
                average, `${stat.pity5} / ${stat.pity4}`,
                stat.remaining === 0 ? 'Участвует' : 'Нужно использовать все молитвы',
            ];
            values.forEach((value) => {
                const cell = document.createElement('td');
                cell.textContent = value;
                row.appendChild(cell);
            });
            body.appendChild(row);
        });
    };

    const updateHistory = (drops) => {
        const history = document.querySelector('#wish-history');
        if (history.querySelector('.muted')) {
            history.replaceChildren();
        }
        [...drops].reverse().forEach((drop) => {
            const badge = document.createElement('span');
            badge.className = `badge wish-rarity-${drop.rarity}`;
            badge.textContent = `${drop.name} · ${drop.rarity}★`;
            history.prepend(badge);
        });
    };

    const showResults = (drops) => {
        results.replaceChildren();
        [...drops].sort((first, second) => second.rarity - first.rarity).forEach((drop, index) => {
            const card = document.createElement('div');
            card.className = `wish-result-card wish-rarity-${drop.rarity}`;
            card.style.animationDelay = `${index * 45}ms`;
            const topStar = document.createElement('span');
            topStar.className = 'wish-card-top-star';
            topStar.textContent = '✧';
            const monogram = document.createElement('span');
            monogram.className = 'wish-item-monogram';
            monogram.textContent = drop.name.split(/\s+/).map((part) => part[0]).join('').slice(0, 2);
            const name = document.createElement('strong');
            name.textContent = drop.name;
            const type = document.createElement('small');
            type.textContent = drop.item_type === 'character' ? 'Персонаж' : 'Оружие';
            const rarity = document.createElement('span');
            rarity.className = 'wish-card-rarity';
            rarity.textContent = '★'.repeat(drop.rarity);
            card.append(topStar, monogram, name, type, rarity);
            if (drop.featured && drop.rarity >= 4) {
                const featured = document.createElement('small');
                featured.className = 'wish-featured-label';
                featured.textContent = 'Featured';
                card.appendChild(featured);
            }
            if (drop.radiant) {
                const radiant = document.createElement('small');
                radiant.className = 'wish-radiant-label';
                radiant.textContent = 'Capturing Radiance';
                card.appendChild(radiant);
            }
            results.appendChild(card);
        });
        animation.hidden = true;
        animation.setAttribute('aria-hidden', 'true');
        skipButton.hidden = true;
    };

    const playAnimation = (drops) => {
        animation.replaceChildren();
        const highestRarity = Math.max(...drops.map((drop) => drop.rarity));
        animation.className = `wish-animation wish-animation-${highestRarity}`;
        drops.forEach((drop, index) => {
            const star = document.createElement('span');
            star.className = `wish-star wish-rarity-${drop.rarity}`;
            star.style.left = `${-12 - index * 3}%`;
            star.style.top = `${-70 - index * 14}px`;
            star.style.animationDelay = `${index * 65}ms`;
            animation.appendChild(star);
        });
        const impact = document.createElement('span');
        impact.className = `wish-impact wish-rarity-${highestRarity}`;
        const ring = document.createElement('span');
        ring.className = 'wish-impact-ring';
        const beam = document.createElement('span');
        beam.className = 'wish-impact-beam';
        impact.append(ring, beam);
        animation.appendChild(impact);
        animation.hidden = false;
        animation.setAttribute('aria-hidden', 'false');
        skipButton.hidden = false;
        const finish = () => {
            window.clearTimeout(animationTimer);
            showResults(drops);
        };
        skipButton.onclick = finish;
        if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
            finish();
        } else {
            animationTimer = window.setTimeout(finish, 2600);
        }
    };

    wishPullButton.addEventListener('click', async () => {
        wishPullButton.disabled = true;
        const body = new FormData();
        body.append('banner_id', wishPullButton.dataset.bannerId);
        body.append('csrf_token', csrfToken);
        try {
            const response = await fetch(`/wishes/${wishPullButton.dataset.eventId}/pull`, {
                method: 'POST',
                body,
                headers: {'X-Requested-With': 'XMLHttpRequest'},
                credentials: 'same-origin',
            });
            const payload = await response.json();
            if (!response.ok) {
                throw new Error(payload.detail || 'Не удалось выполнить молитву');
            }
            updateParticipant(payload.participant);
            updateStats(payload.stats);
            updateHistory(payload.drops);
            playAnimation(payload.drops);
        } catch (error) {
            showWishError(error.message);
            wishPullButton.disabled = false;
        }
    });
}
