const semanticMap = document.querySelector('[data-semantic-map]');
const wordCloud = document.querySelector('[data-word-cloud]');

if (semanticMap && wordCloud) {
    const detail = document.querySelector('[data-word-detail]');
    const detailTitle = detail.querySelector('[data-detail-title]');
    const detailCount = detail.querySelector('[data-detail-count]');
    const detailRelated = detail.querySelector('[data-detail-related]');
    const mapWords = [...semanticMap.querySelectorAll('[data-word]')];
    const cloudWords = [...wordCloud.querySelectorAll('[data-word]')];
    const edges = [...semanticMap.querySelectorAll('line[data-source]')];
    const formatNumber = (value) => new Intl.NumberFormat('ru-RU').format(value);

    const showWord = (word) => {
        const mapWord = mapWords.find((node) => node.dataset.word === word);
        const cloudWord = cloudWords.find((node) => node.dataset.word === word);
        const source = mapWord || cloudWord;
        if (!source) {
            return;
        }
        const related = mapWord?.dataset.related ? mapWord.dataset.related.split('|') : [];
        const connected = new Set([word, ...related]);
        mapWords.forEach((node) => {
            node.classList.remove('is-related');
            node.classList.toggle('is-active', node.dataset.word === word);
            node.classList.toggle('is-muted', !connected.has(node.dataset.word));
        });
        cloudWords.forEach((node) => {
            node.classList.toggle('is-active', node.dataset.word === word);
            node.classList.toggle('is-muted', mapWord && node.dataset.word !== word);
        });
        edges.forEach((edge) => {
            const isConnected = edge.dataset.source === word || edge.dataset.target === word;
            edge.classList.toggle('is-active', isConnected);
            edge.classList.toggle('is-muted', !isConnected);
        });
        detailTitle.textContent = word;
        detailCount.textContent = `Встречается в ${formatNumber(source.dataset.count)} сообщениях`;
        detailRelated.replaceChildren();
        if (mapWord) {
            const neighbors = new Map(mapWords.map((node) => [node.dataset.word, node]));
            related.forEach((neighbor) => {
                const edge = edges.find((line) => (
                    (line.dataset.source === word && line.dataset.target === neighbor)
                    || (line.dataset.target === word && line.dataset.source === neighbor)
                ));
                const item = document.createElement('li');
                const label = document.createElement('span');
                const count = document.createElement('small');
                label.textContent = neighbor;
                count.textContent = edge?.querySelector('title')?.textContent.split(': ').pop() || '';
                item.append(label, count);
                item.addEventListener('click', () => showWord(neighbor));
                neighbors.get(neighbor)?.classList.add('is-related');
                detailRelated.appendChild(item);
            });
        } else {
            const item = document.createElement('li');
            item.className = 'word-detail-empty';
            item.textContent = 'Слово входит в облако, но не в число 48 узлов карты.';
            detailRelated.appendChild(item);
        }
    };

    const reset = () => {
        mapWords.forEach((node) => node.classList.remove('is-active', 'is-muted', 'is-related'));
        cloudWords.forEach((node) => node.classList.remove('is-active', 'is-muted'));
        edges.forEach((edge) => edge.classList.remove('is-active', 'is-muted'));
        const first = mapWords[0];
        if (first) {
            showWord(first.dataset.word);
            mapWords.forEach((node) => node.classList.remove('is-active', 'is-muted', 'is-related'));
            cloudWords.forEach((node) => node.classList.remove('is-active', 'is-muted'));
            edges.forEach((edge) => edge.classList.remove('is-active', 'is-muted'));
        }
    };

    [...mapWords, ...cloudWords].forEach((node) => {
        node.addEventListener('click', () => showWord(node.dataset.word));
        node.addEventListener('keydown', (event) => {
            if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault();
                showWord(node.dataset.word);
            }
        });
    });
    detail.querySelector('[data-insight-reset]').addEventListener('click', reset);
}
